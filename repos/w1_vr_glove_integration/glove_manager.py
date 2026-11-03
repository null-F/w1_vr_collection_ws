#!/usr/bin/env python3
"""Own the glove process group; speak calibration events without blocking ROS."""
import collections
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).resolve().parent
RUNTIME = Path('/home/dexforce/linkerhand/runtime/vr_glove')
VOICE = 'http://192.168.20.21:8766/voice_agent/speak'
EVENT = 'LINKERHAND_GLOVE_EVENT '


class Voice:
    def __init__(self):
        self.queue = queue.Queue()
        self.epoch = 0
        threading.Thread(target=self.run, daemon=True).start()

    def clear(self):
        self.epoch += 1

    def say(self, text):
        self.queue.put((self.epoch, text))

    def run(self):
        while True:
            epoch, text = self.queue.get()
            if epoch != self.epoch:
                continue
            try:
                payload = {'type': 'text', 'params': {'text': text}, 'blocking': True}
                req = urllib.request.Request(VOICE, json.dumps(payload, ensure_ascii=False).encode(),
                    {'Content-Type': 'application/json; charset=utf-8'}, method='POST')
                with urllib.request.urlopen(req, timeout=25) as response:
                    result = json.load(response)
                if result.get('code') != 0 or result.get('data', {}).get('status') != 'ok':
                    raise RuntimeError(str(result))
                print('VOICE_OK', text, flush=True)
            except Exception as exc:
                print('VOICE_FAILED', text, str(exc), flush=True)


class Manager:
    def __init__(self, command=None, voice=None, runtime=RUNTIME):
        self.command = command or ['bash', str(HERE / 'run_gloves.sh')]
        self.voice = voice if voice is not None else Voice()
        self.runtime = Path(runtime)
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.proc = None
        self.phase = 'stopped'
        self.stage = None
        self.session = None
        self.requests = collections.OrderedDict()
        self.worker = None
        self._save()

    def status(self):
        with self.lock:
            return {'phase': self.phase, 'stage': self.stage, 'session': self.session,
                    'pid': self.proc.pid if self.proc else None}

    def _save(self):
        data = json.dumps(self.status(), ensure_ascii=False)
        tmp = self.runtime / 'state.json.tmp'
        tmp.write_text(data)
        tmp.replace(self.runtime / 'state.json')

    def toggle(self, request_id):
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 160:
            raise ValueError('A bounded request_id is required')
        with self.lock:
            if request_id in self.requests:
                return self.status()
            self.requests[request_id] = time.monotonic()
            while len(self.requests) > 128:
                self.requests.popitem(last=False)
            if self.proc is not None:
                self.stop()
                return self.status()
            self.voice.clear()
            self.phase = 'starting'
            self.stage = None
            self.session = str(time.time_ns())
            log = self.runtime / ('glove_' + self.session + '.log')
            env = dict(os.environ, PYTHONUNBUFFERED='1')
            try:
                self.proc = subprocess.Popen(self.command, env=env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    encoding='utf-8', errors='replace', bufsize=1, start_new_session=True)
            except Exception:
                self.phase = 'failed'
                self._save()
                self.voice.say('手套启动失败，请检查设备连接。')
                raise
            proc = self.proc
            self._save()
            self.worker = threading.Thread(target=self._watch, args=(proc, log), daemon=True)
            self.worker.start()
            return self.status()

    def _event(self, proc, event):
        with self.lock:
            if self.proc is not proc or self.phase == 'stopping':
                return
            kind = event.get('event')
            if kind == 'stage':
                stage = event.get('stage')
                texts = {'fist': '请双手握拳并保持。', 'opose': '请双手保持O型手势。',
                         'original': '请双手五指张开并保持。',
                         'open_full': '请双手五指完全张开并伸直。',
                         'adduct': '请双手五指并拢伸直。',
                         'thumbs_up': '请双手做点赞手势。',
                         'pinch': '请双手五指指尖聚拢捏在一起。',
                         'thumb_flex': '请双手拇指指尖弯向拇指根。'}
                if stage in texts and stage != self.stage:
                    self.phase = 'calibrating'
                    self.stage = stage
                    # The glove wrapper speaks before entering each calibration step.
            elif kind == 'ready':
                if self.phase != 'following':
                    self.phase = 'following'
                    self.voice.say('标定完成，手套遥操已启动。')
            elif kind == 'failed':
                self.phase = 'failed'
                self.voice.clear()
                self.voice.say('手套标定失败，请检查手套后重新启动。')
            self._save()
            print('GLOVE_EVENT', json.dumps(event, ensure_ascii=False), flush=True)

    @staticmethod
    def _signal_group(proc, sig):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass

    def _watch(self, proc, log):
        try:
            with log.open('a') as output:
                for line in proc.stdout:
                    output.write(line)
                    output.flush()
                    if EVENT in line:
                        try:
                            self._event(proc, json.loads(line.split(EVENT, 1)[1]))
                        except (ValueError, TypeError, AttributeError) as exc:
                            print('EVENT_PARSE_ERROR', str(exc), flush=True)
            proc.wait()
        finally:
            # Also remove a leftover format bridge if its shell exited early.
            self._signal_group(proc, signal.SIGTERM)
            time.sleep(0.15)
            self._signal_group(proc, signal.SIGKILL)
            with self.lock:
                if self.proc is proc:
                    stopped = self.phase == 'stopping'
                    failed = self.phase == 'failed'
                    self.proc = None
                    self.phase = 'stopped' if stopped else 'failed'
                    self.stage = None
                    self._save()
                    if stopped:
                        self.voice.say(self.stop_phrase)
                    if not stopped and not failed:
                        self.voice.clear()
                        self.voice.say('手套程序已退出，请检查手套连接后重新启动。')
            print('GLOVE_EXIT', proc.pid, proc.returncode, flush=True)

    def stop(self):
        with self.lock:
            proc = self.proc
            if proc is None or self.phase == 'stopping':
                return
            calibrating = self.phase in ('starting', 'calibrating')
            self.phase = 'stopping'
            self._save()
            self.voice.clear()
            self.stop_phrase = '已取消手套标定。' if calibrating else '已停止手套遥操。'
            threading.Thread(target=self._terminate, args=(proc,), daemon=True).start()

    def _terminate(self, proc):
        self._signal_group(proc, signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._signal_group(proc, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._signal_group(proc, signal.SIGKILL)

    def close(self):
        self.stop()
        if self.worker:
            self.worker.join(timeout=10)


def main():
    manager = Manager()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, value):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.reply(200, manager.status()) if self.path == '/status' else self.reply(404, {'error': 'not found'})

        def do_POST(self):
            if self.path != '/toggle':
                self.reply(404, {'error': 'not found'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError('Invalid request size')
                payload = json.loads(self.rfile.read(length))
                result = manager.toggle(payload.get('request_id'))
                self.reply(200, result)
            except (ValueError, AttributeError, TypeError) as exc:
                self.reply(400, {'error': str(exc)})
            except Exception as exc:
                print('TOGGLE_FAILED', str(exc), flush=True)
                self.reply(500, {'error': str(exc)})

        def log_message(self, format, *args):
            print('MANAGER_HTTP', format % args, flush=True)

    server = ThreadingHTTPServer(('127.0.0.1', 18770), Handler)
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print('Glove manager ready on 127.0.0.1:18770; waiting for X', flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        manager.close()
        server.server_close()


if __name__ == '__main__':
    main()
