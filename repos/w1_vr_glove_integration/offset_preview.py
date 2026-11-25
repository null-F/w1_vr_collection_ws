#!/usr/bin/env python3
"""Loopback-only, offline offset tuning UI. Saves config; never sends motion."""
import argparse
import hmac
import json
import math
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from controller_offsets import CONFIG, ControllerOffsets
import operator_state as signals
from offset_calibration import sample, solve
from offset_profiles import ProfileStore

ASSET = Path(__file__).parent / 'frontend/offset_preview.html'


def validate(data):
    if not isinstance(data, dict) or type(data.get('enabled')) is not bool:
        raise ValueError('enabled 必须为布尔值')
    result = {'enabled': data['enabled']}
    for side in ('left', 'right'):
        hand = data.get(side, {})
        result[side] = {}
        for field, limit in (('translation_m', 0.5), ('rotation_xyz_deg', 180)):
            value = hand.get(field)
            if (not isinstance(value, list) or len(value) != 3 or
                any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > limit for v in value)):
                raise ValueError(f'{side}.{field} 需要三个有限数值，范围 ±{limit}')
            result[side][field] = value
    return result


def save_config(path, data):
    data = validate(data)
    # Same transformation parser as the actual teleop path, before publishing the file.
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    temporary = path.with_name(path.name + '.preview-' + secrets.token_hex(6) + '.tmp')
    try:
        temporary.write_text(content)
        ControllerOffsets(temporary)
        if path.exists():
            backup = signals.ROOT / 'runtime/backups/controller-offset-preview'
            backup.mkdir(parents=True, exist_ok=True)
            (backup / f'{time.time_ns()}.json').write_bytes(path.read_bytes())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return data


def make_handler(path=CONFIG, poses=signals.SIGNALS / 'controller_preview.json'):
    token, lock = secrets.token_urlsafe(32), threading.Lock()
    capture_lock, pairs = threading.Lock(), {}
    profiles = ProfileStore(signals.ROOT / "config/w1/controller_offset_profiles")
    profiles.seed(validate(json.loads(path.read_text())))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass

        def reply(self, value, status=200, content_type='application/json; charset=utf-8'):
            raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def local_host(self):
            # Block DNS rebinding when running on localhost or behind SSH forwarding.
            return self.headers.get('Host', '').split(':')[0] in ('127.0.0.1', 'localhost')

        def do_GET(self):
            if not self.local_host():
                return self.reply({'error': '请通过 localhost 访问'}, 403)
            route = urlsplit(self.path).path
            if route == '/':
                page = ASSET.read_text().replace('__TOKEN__', token)
                return self.reply(page.encode(), content_type='text/html; charset=utf-8')
            if route == '/api/config':
                try:
                    with lock:
                        config = validate(json.loads(path.read_text()))
                    return self.reply({'config': config, 'path': str(path), 'save_effect': '保存后需重新加载 VR 服务才用于遥操；本页面不执行重启或运动。'})
                except (OSError, ValueError) as exc:
                    return self.reply({'error': str(exc)}, 500)
            if route == '/api/profiles':
                records, warnings = profiles.listing()
                return self.reply(dict(records=records, warnings=warnings))
            if route == '/api/poses':
                data = signals.read(poses)
                stamp = data.get('monotonic')
                age = time.monotonic() - stamp if type(stamp) in (int, float) else None
                live = age is not None and 0 <= age < 0.5
                return self.reply({'live': live, 'age_s': age, 'poses': data.get('poses') if live else None})
            return self.reply({'error': 'Not found'}, 404)

        def do_POST(self):
            if not self.local_host() or not hmac.compare_digest(self.headers.get('X-Preview-Token', ''), token):
                return self.reply({'error': '请求校验失败，请重新打开页面'}, 403)
            if self.path not in ('/api/config', '/api/calibration/capture', '/api/profiles', '/api/profiles/average'):
                return self.reply({'error': 'Not found'}, 404)
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 8192:
                    raise ValueError('请求大小无效')
                data = json.loads(self.rfile.read(length))
                if self.path == '/api/profiles':
                    if not isinstance(data, dict):
                        raise ValueError('映射组请求无效')
                    if 'source_ids' in data:
                        result = profiles.average(data['source_ids'], data.get('side'))
                        record = profiles.save(data.get('name'), 'average', **result)
                    else:
                        record = profiles.save(data.get('name'), 'configuration', config=validate(data.get('config')))
                    return self.reply(dict(record=record, message='映射组已归档；遥操配置未更改。'))
                if self.path == '/api/profiles/average':
                    if not isinstance(data, dict):
                        raise ValueError('平均映射请求无效')
                    return self.reply(dict(result=profiles.average(data.get('ids'), data.get('side'))))
                if self.path == '/api/calibration/capture':
                    return self.capture(data)
                with lock:
                    config = save_config(path, data)
                return self.reply({'config': config, 'message': '已备份并保存配置；未重启 VR，未发送运动指令。'})
            except (ValueError, OSError, TypeError) as exc:
                return self.reply({'error': str(exc)}, 400)
        def capture(self, data):
            if not isinstance(data, dict) or data.get('side') not in ('left', 'right') or data.get('stage') not in ('palm', 'back'):
                return self.reply({'error': '请选择左/右手及掌心/手背采集步骤'}, 400)
            if not capture_lock.acquire(blocking=False):
                return self.reply({'error': '已有采集正在进行，请稍后重试'}, 409)
            try:
                now = time.monotonic()
                for key in list(pairs):
                    if now - pairs[key]['palm']['captured_monotonic'] > 600:
                        del pairs[key]
                side, stage = data['side'], data['stage']
                if stage == 'palm':
                    if len(pairs) >= 64:
                        del pairs[next(iter(pairs))]
                    captured = sample(poses, side)
                    key = secrets.token_urlsafe(24)
                    pairs[key] = dict(side=side, palm=captured)
                    return self.reply(dict(pair_id=key, stage=stage, summary=captured['summary']))
                key = data.get('pair_id')
                pair = pairs.get(key) if isinstance(key, str) else None
                if pair is None or pair['side'] != side:
                    raise ValueError('请先为当前手采集掌心参考')
                captured = sample(poses, side, expected_stream=pair['palm']['stream_id'])
                result = solve(pair['palm'], captured)
                archive = signals.ROOT / 'runtime/offset_calibration'
                archive.mkdir(parents=True, exist_ok=True)
                archive_path = archive / f'{time.time_ns()}-{side}.json'
                archive_path.write_text(json.dumps(
                    dict(side=side, palm=pair['palm'], back=captured, result=result), ensure_ascii=False, indent=2))
                record = profiles.save(data.get('name') or ('左手' if side == 'left' else '右手')+'采样组',
                    'capture', side=side, offset=result['offset'], source='live_capture',
                    sample_path=str(archive_path), quality=dict(palm=pair['palm']['summary'], back=captured['summary']))
                return self.reply(dict(pair_id=key, stage=stage, summary=captured['summary'], result=result, record=record))
            except (ValueError, OSError, KeyError, TypeError) as exc:
                return self.reply({'error': str(exc)}, 400)
            finally:
                capture_lock.release()
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18772)
    parser.add_argument('--config', type=Path, default=CONFIG)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(args.config))
    print(f'Offset preview: http://127.0.0.1:{args.port}/ (read-only live poses; config saves require VR reload)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
