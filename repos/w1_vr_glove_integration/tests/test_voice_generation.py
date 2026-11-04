"""Regression for the cmn -> English-pinyin fallback and implicit encoding bug."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'repos/w1_vr_glove_integration'))
import generate_voice_assets as generator
import local_voice

# Captured from the affected espeak-ng 1.51 on the exact delivered Chinese text.
ENGLISH_PINYIN = "(en)SV55f'o@55_| dZV55f'o@55_| keI55Tr'i:55_|(cmn)_|"
BAD_PUNCTUATION = "s.'u51_| tS;'y51_| _:(en)eI33_|tI11ld@11_|(cmn)_|"
MANDARIN = "s.'u51_| tS;'y51_| tsh'ai21_| tS;'i35_| j'i35_| p'Au21_| tsh'u@35n_|"


@pytest.mark.parametrize('trace', [ENGLISH_PINYIN, BAD_PUNCTUATION, '(en-us)hello55',
                                  '(fr)bonjour35', '', 'hello'])
def test_reject_foreign_empty_or_toneless_synthesis(trace):
    with pytest.raises(ValueError):
        generator.validate_mandarin_phonemes(trace)


def test_accept_mandarin_trace():
    generator.validate_mandarin_phonemes(MANDARIN)


@pytest.fixture
def synthesis(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    config = root / 'config/w1'
    config.mkdir(parents=True)
    (config / 'voice_prompts.json').write_text(
        json.dumps({'record_saved': '数据采集已保存。'}, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(generator, 'ROOT', root)
    log = tmp_path / 'input.json'
    monkeypatch.setenv('TEST_SYNTHESIS_LOG', str(log))
    engine = tmp_path / 'espeak-ng'
    engine.write_text(f'#!{sys.executable}\n' + r'''
import json, os, pathlib, sys, wave
if '--version' in sys.argv:
    print('fake espeak-ng for argument regression only')
    sys.exit(0)
text = sys.stdin.buffer.read().decode('utf-8')
pathlib.Path(os.environ['TEST_SYNTHESIS_LOG']).write_text(json.dumps({'args': sys.argv[1:], 'text': text}))
path = sys.argv[sys.argv.index('-w') + 1]
with wave.open(path, 'wb') as audio:
    audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
    audio.writeframes(b'\x01\x00' * 800)
print(os.environ['TEST_SYNTHESIS_TRACE'])
''')
    engine.chmod(0o755)
    return engine, tmp_path / 'candidate', log


def test_generation_uses_explicit_utf8_pinyin_voice_and_same_call_trace(synthesis, monkeypatch):
    engine, output, log = synthesis
    monkeypatch.setenv('TEST_SYNTHESIS_TRACE', MANDARIN)
    generator.main(['--engine', str(engine), '--output', str(output)])
    call = json.loads(log.read_text())
    args = call['args']
    assert args[args.index('-v') + 1] == 'cmn-latn-pinyin'
    assert args[args.index('-b') + 1] == '1'
    assert '-x' in args and '-w' in args and '--stdin' in args
    assert call['text'] == '数据采集已保存。'
    manifest = json.loads((output / 'manifest.json').read_text())
    assert manifest['schema_version'] == 2
    assert manifest['prompts']['record_saved']['phonemes'] == MANDARIN
    assert manifest['prompts']['record_saved']['sha256'] == hashlib.sha256((output / 'record_saved.wav').read_bytes()).hexdigest()


@pytest.mark.parametrize('trace', [ENGLISH_PINYIN, BAD_PUNCTUATION])
def test_failed_language_check_does_not_publish_manifest(synthesis, monkeypatch, trace):
    engine, output, _ = synthesis
    monkeypatch.setenv('TEST_SYNTHESIS_TRACE', trace)
    with pytest.raises(ValueError, match='Non-Mandarin'):
        generator.main(['--engine', str(engine), '--output', str(output)])
    assert not (output / 'manifest.json').exists()


def test_all_delivered_audio_has_checked_trace_and_corrected_settings():
    assets = ROOT / 'repos/w1_vr_glove_integration/audio/zh_CN'
    manifest = json.loads((assets / 'manifest.json').read_text())
    assert manifest['schema_version'] == 2
    assert manifest['generator']['voice'] == 'cmn-latn-pinyin'
    assert manifest['generator']['input_encoding'] == 'UTF-8 (engine -b 1)'
    assert len(manifest['prompts']) == 20
    for entry in manifest['prompts'].values():
        generator.validate_mandarin_phonemes(entry['phonemes'])
        assert hashlib.sha256((assets / entry['file']).read_bytes()).hexdigest() == entry['sha256']
    assert manifest['prompts']['record_saved']['sha256'] != 'b1bbc74b847e12f408944faddab1278a2e1ed6f38db07695a03622b69a031acc'


def test_runtime_rejects_old_schema_instead_of_accepting_faulty_bank(tmp_path):
    assets = tmp_path / 'old-bank'
    assets.mkdir()
    (assets / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'prompts': {}}))
    config = tmp_path / 'voice.json'
    config.write_text(json.dumps({'assets': str(assets), 'server': 'unix:/tmp/pulse/native',
                                 'sink': 'alsa_output.usb-test', 'lock_wait_seconds': 1,
                                 'playback_grace_seconds': 1, 'probe_timeout_seconds': 1}))
    with pytest.raises(local_voice.VoiceError, match='obsolete'):
        local_voice.LocalPlayer(config=config, executable='unused', probe_executable='unused')
