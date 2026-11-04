#!/usr/bin/env python3
"""Fixed PC1 speech assets, with no HTTP, ROS, runtime synthesis or extra service.

All cooperating processes use the same advisory lock. It is held until the playback process
has exited, including cancellation/error paths; unrelated vendor audio is not
controlled by this lock. Importing this module neither writes nor opens audio.
"""
from __future__ import annotations

import argparse
from collections import deque
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'config/w1/voice_prompts.json'
CONFIG = ROOT / 'config/w1/voice.json'
LOCK = ROOT / 'runtime/voice/playback.lock'


class VoiceError(RuntimeError):
    pass


class PlaybackCancelled(VoiceError):
    pass


def _cancelled(cancel):
    if cancel.is_set():
        raise PlaybackCancelled('Local speech cancelled')


def _positive(value, name):
    value = float(value)
    if not math.isfinite(value) or not 0 < value <= 60:
        raise VoiceError(f'Invalid {name}: expected 0 < seconds <= 60')
    return value


class LocalPlayer:
    def __init__(self, *, config=None, catalog=None, lock_path=None,
                 executable=None, probe_executable=None):
        settings = json.loads(Path(config or os.environ.get('W1_VOICE_CONFIG', CONFIG)).read_text())
        self.sink = os.environ.get('W1_VOICE_SINK', settings['sink'])
        if (not isinstance(self.sink, str)
                or not re.fullmatch(r'[A-Za-z0-9_.:-]+', self.sink)
                or self.sink.lower() == 'default' or self.sink.isdecimal()):
            raise VoiceError('An explicit named PulseAudio output sink is required; no default/index')
        self.server = os.environ.get('W1_VOICE_PULSE_SERVER', settings['server'])
        self.server = self.server.replace('{uid}', str(os.getuid()))
        if (not self.server.startswith('unix:/') or any(c.isspace() for c in self.server)
                or '\0' in self.server):
            raise VoiceError('Offline speech requires one local unix:/ PulseAudio socket, not TCP')
        self.assets = (ROOT / settings['assets']).resolve()
        self.lock_path = Path(lock_path) if lock_path is not None else LOCK
        self.lock_wait = _positive(settings['lock_wait_seconds'], 'lock_wait_seconds')
        self.grace = _positive(settings['playback_grace_seconds'], 'playback_grace_seconds')
        self.probe_timeout = _positive(settings['probe_timeout_seconds'], 'probe_timeout_seconds')
        self.executable = executable or shutil.which('paplay')
        self.probe_executable = probe_executable or shutil.which('pactl')
        if not self.executable or not self.probe_executable:
            raise VoiceError('paplay/pactl missing; install pulseaudio-utils on PC1 before deployment')
        self.catalog = json.loads(Path(catalog or CATALOG).read_text())
        manifest = json.loads((self.assets / 'manifest.json').read_text())
        if manifest.get('schema_version') != 2:
            raise VoiceError('Unsupported/obsolete speech manifest version; replace the complete WAV bank and manifest')
        self.entries = manifest['prompts']
        if not self.catalog or set(self.entries) != set(self.catalog):
            raise VoiceError('Speech manifest does not match the prompt catalog')
        if len(set(self.catalog.values())) != len(self.catalog):
            raise VoiceError('Duplicate speech texts in catalog')
        for key, text in self.catalog.items():
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', key) or not isinstance(text, str) or not text:
                raise VoiceError('Invalid speech catalog entry')
            entry = self.entries[key]
            if entry['text'] != text or entry['file'] != key + '.wav':
                raise VoiceError(f'Speech text/file mismatch: {key}')
        self.by_text = {text: key for key, text in self.catalog.items()}

    def validate(self, key):
        if key not in self.entries:
            raise VoiceError(f'Unknown local prompt: {key}')
        entry = self.entries[key]
        path = (self.assets / entry['file']).resolve()
        if not path.is_relative_to(self.assets):
            raise VoiceError(f'Speech asset escapes its directory: {key}')
        if not 44 < path.stat().st_size <= 4 * 1024 * 1024:
            raise VoiceError(f'Invalid speech asset size: {key}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise VoiceError(f'Speech asset checksum mismatch: {key}')
        with wave.open(str(path), 'rb') as audio:
            channels, width, rate, frames = (audio.getnchannels(), audio.getsampwidth(),
                                           audio.getframerate(), audio.getnframes())
            if audio.getcomptype() != 'NONE' or width != 2 or channels not in (1, 2):
                raise VoiceError(f'Speech must be PCM16 mono/stereo WAV: {key}')
            if not 8000 <= rate <= 96000 or not 0 < frames / rate <= 20:
                raise VoiceError(f'Invalid speech duration/sample rate: {key}')
            if len(audio.readframes(frames)) != frames * channels * width:
                raise VoiceError(f'Truncated speech asset: {key}')
        return path, frames / rate

    def check(self):
        durations = {key: round(self.validate(key)[1], 3) for key in self.catalog}
        return {'backend': 'local-wav-pulse', 'player': str(self.executable),
                'server': self.server, 'sink': self.sink,
                'prompts': len(durations), 'durations_seconds': durations,
                'note': 'Files/config only: no sound device opened; playback permissions unverified'}

    @contextmanager
    def _locked(self, cancel, deadline):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Never unlink this file: waiters must continue locking the same inode.
        with self.lock_path.open('a+b') as lock:
            while True:
                _cancelled(cancel)
                if time.monotonic() >= deadline:
                    raise VoiceError('Timed out waiting for local speech playback slot')
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    cancel.wait(.02)
            try:
                _cancelled(cancel)
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _stop(proc):
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=.5)
        except ProcessLookupError:
            proc.wait(timeout=.5)

    def _execute(self, command, cancel, timeout):
        # No shell, and no changes to system volume/default sinks/modules. A
        # cancellable child is also used for pactl, not a blocking network call.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            _cancelled(cancel)
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                                    stderr=errors, close_fds=True)
            try:
                end = time.monotonic() + timeout
                while proc.poll() is None:
                    _cancelled(cancel)
                    if time.monotonic() >= end:
                        raise VoiceError(f'Local audio command timed out: {Path(command[0]).name}')
                    cancel.wait(.02)
                _cancelled(cancel)
                if proc.returncode != 0:
                    errors.seek(0)
                    detail = errors.read(2048).decode('utf-8', 'replace').strip()
                    raise VoiceError(f'{Path(command[0]).name} failed ({proc.returncode}): {detail}')
                output.seek(0)
                return output.read(128 * 1024).decode('utf-8', 'replace')
            finally:
                self._stop(proc)

    def check_output(self, cancel=None):
        """Read-only query of PC1 sinks. No playback, capture, or module loading."""
        cancel = cancel if cancel is not None else threading.Event()
        result = self._execute([str(self.probe_executable), '--server=' + self.server,
                                'list', 'short', 'sinks'], cancel, self.probe_timeout)
        if not any(len(parts := line.split()) >= 2 and parts[1] == self.sink
                   for line in result.splitlines()):
            raise VoiceError(f'Configured PC1 sink is absent: {self.sink}; no default fallback')
        return {'server': self.server, 'sink': self.sink, 'present': True,
                'note': 'Sink exists; audibility, mute, volume and routing stability still need target checks'}

    def play(self, text, cancel=None, *, deadline=None):
        cancel = cancel if cancel is not None else threading.Event()
        _cancelled(cancel)
        try:
            key = self.by_text[text]
        except KeyError:
            raise VoiceError(f'No packaged audio for text: {text}') from None
        path, duration = self.validate(key)
        lock_deadline = time.monotonic() + self.lock_wait
        if deadline is not None:
            lock_deadline = min(lock_deadline, deadline)
        with self._locked(cancel, lock_deadline):
            self.check_output(cancel)
            _cancelled(cancel)
            if time.monotonic() >= lock_deadline:
                raise VoiceError('Speech expired before playback')
            # Pin both the local server and the real PC1 sink. Ignore any
            # inherited PULSE_SERVER/PULSE_SINK pointing at PC2 or onboard audio.
            # Inherit the glove process group so X group signals stop playback.
            self._execute([str(self.executable), '--playback', '--server=' + self.server,
                           '--device=' + self.sink, '--client-name=linkerhand-local-voice',
                           '--stream-name=' + key, str(path)], cancel, duration + self.grace)


def play_text(text, cancel=None, *, deadline=None):
    LocalPlayer().play(text, cancel, deadline=deadline)


class Voice:
    """Non-blocking status speech. clear() cancels queued AND active audio.

    Queues are per owner (glove manager / MCAP); the playback lock is global
    within this deployment. Full/stale queues are dropped, never allowed to
    block control callbacks. Stopping motion/recording must not await speech.
    """
    def __init__(self, player=None, *, ttl=12.0, capacity=32):
        self.player = player or play_text
        self.ttl = _positive(ttl, 'queue ttl')
        if capacity < 1:
            raise ValueError('Speech queue capacity must be positive')
        self.capacity = capacity
        self.pending = deque()
        self.condition = threading.Condition()
        self.active = None
        self.closed = False
        self.worker = threading.Thread(target=self.run, daemon=True, name='w1-local-voice')
        self.worker.start()

    def clear(self):
        with self.condition:
            self.pending.clear()
            if self.active is not None:
                self.active.set()

    def say(self, text):
        with self.condition:
            if self.closed:
                return
            if len(self.pending) >= self.capacity:
                self.pending.popleft()
                print('VOICE_DROPPED queue_full', flush=True)
            self.pending.append((text, time.monotonic() + self.ttl))
            self.condition.notify()

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending)
                if self.closed:
                    return
                text, deadline = self.pending.popleft()
                if time.monotonic() >= deadline:
                    print('VOICE_DROPPED expired', text, flush=True)
                    continue
                cancel = self.active = threading.Event()
            try:
                self.player(text, cancel, deadline=deadline)
                print('VOICE_OK', text, flush=True)
            except PlaybackCancelled:
                print('VOICE_CANCELLED', text, flush=True)
            except Exception as exc:
                print('VOICE_FAILED', text, str(exc), flush=True)
            finally:
                with self.condition:
                    self.active = None

    def close(self):
        with self.condition:
            self.closed = True
            self.clear()
            self.condition.notify_all()
        self.worker.join(timeout=2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true', help='Validate assets/config only, no playback')
    action.add_argument('--check-output', action='store_true',
                        help='Read-only PC1 PulseAudio sink query, no playback')
    action.add_argument('--list', action='store_true', help='List fixed prompt IDs and texts')
    action.add_argument('--play', metavar='PROMPT_ID', help='Explicitly play one prompt on PC1')
    args = parser.parse_args(argv)
    try:
        player = LocalPlayer()
        if args.check:
            print(json.dumps(player.check(), ensure_ascii=False, indent=2))
        elif args.check_output:
            print(json.dumps(player.check_output(), ensure_ascii=False, indent=2))
        elif args.list:
            print(json.dumps(player.catalog, ensure_ascii=False, indent=2))
        else:
            player.play(player.catalog[args.play])
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f'LOCAL_VOICE_FAILED: {exc}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
