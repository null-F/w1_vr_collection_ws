#!/usr/bin/env python3
"""Build basic Mandarin WAV prompts offline; never used during robot startup.

Requires espeak-ng only on the asset-generation machine, not on the robot.
Use --output to build a separate candidate bank, then listen/review before
replacing production assets. No downloads and no loudspeaker output.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import wave

ROOT = Path(__file__).resolve().parents[2]


def validate_mandarin_phonemes(phonemes):
    """Reject detected language fallback, not just a Chinese-looking voice name.

    This is a synthesis-path check, NOT listening/ASR or an intelligibility test.
    In the affected 1.51 data, cmn can re-read substituted pinyin as English;
    cmn-latn-pinyin avoids that path. Explicit UTF-8 also prevents punctuation
    from being misread as Latin characters.
    """
    switches = re.findall(r'\(([a-zA-Z][a-zA-Z0-9-]*)\)', phonemes)
    foreign = [language for language in switches if language not in ('cmn', 'cmn-latn-pinyin', 'zh')]
    if not phonemes.strip() or foreign:
        raise ValueError(f'Non-Mandarin/empty phoneme output; language switches={foreign}')
    if not re.search(r'(?:55|35|214|21|51|11)', phonemes):
        raise ValueError('No Mandarin tone markers in phoneme output')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', default='espeak-ng')
    parser.add_argument('--voice', default='cmn-latn-pinyin')
    parser.add_argument('--speed', type=int, default=170)
    parser.add_argument('--output', type=Path, required=True,
                        help='New/empty directory for candidate WAVs and manifest')
    args = parser.parse_args(argv)
    engine = shutil.which(args.engine)
    if not engine:
        parser.error('espeak-ng is not installed on this asset-generation machine')
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Output directory must be empty; do not overwrite a running audio bank')
    catalog = json.loads((ROOT / 'config/w1/voice_prompts.json').read_text(encoding='utf-8'))
    version = subprocess.run([engine, '--version'], check=True, capture_output=True,
                             encoding='utf-8', timeout=10).stdout.strip()
    args.output.mkdir(parents=True, exist_ok=True)
    entries = {}
    for key, text in catalog.items():
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', key) or not isinstance(text, str) or not text:
            raise ValueError('Invalid prompt ID/text in catalog')
        path = args.output / (key + '.wav')
        # One invocation generates both WAV and its phoneme trace, using exactly
        # the same voice and UTF-8 input. Never publish a manifest on failure.
        result = subprocess.run([engine, '-v', args.voice, '-b', '1', '-s', str(args.speed),
                                 '-x', '-w', str(path), '--stdin'],
                                input=text, encoding='utf-8', check=True,
                                capture_output=True, timeout=30)
        phonemes = result.stdout.strip()
        validate_mandarin_phonemes(phonemes)
        with wave.open(str(path), 'rb') as audio:
            duration = audio.getnframes() / audio.getframerate()
        entries[key] = {'text': text, 'file': path.name,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'duration_seconds': round(duration, 3), 'phonemes': phonemes}
    manifest = {'schema_version': 2, 'generator': {'engine': version, 'voice': args.voice,
                'speed': args.speed, 'input_encoding': 'UTF-8 (engine -b 1)',
                'validation': 'Per-prompt Mandarin tone markers and no foreign-language fallback; not an acoustic/listening test.',
                'note': 'Basic synthetic Mandarin. Target intelligibility not yet accepted.'},
                'prompts': entries}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Generated {len(entries)} prompts in {args.output}; no playback performed')


if __name__ == '__main__':
    main()
