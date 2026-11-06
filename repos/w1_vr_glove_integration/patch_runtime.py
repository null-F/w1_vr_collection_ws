"""Narrow runtime overlays for vendor low-frequency input and one static JS asset."""
import asyncio
import functools
import json
from pathlib import Path
import traceback
import urllib.request

HERE = Path(__file__).resolve().parent
MANAGER = 'http://127.0.0.1:18770/toggle'


class GloveControl:
    def __init__(self, request_id):
        self.request_id = request_id


class McapCancel:
    pass


def send_toggle(request_id):
    request = urllib.request.Request(MANAGER,
        json.dumps({'request_id': request_id}).encode(),
        {'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.load(response)


def patch_low_frequency(module):
    original_decode = module.decode_message
    def decode(raw):
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            return original_decode(raw)
        if isinstance(value, dict) and value.get('type') == 'linkerhand_mcap_cancel':
            return McapCancel()
        if isinstance(value, dict) and value.get('type') == 'linkerhand_glove_control':
            request_id = value.get('request_id')
            if value.get('action') == 'toggle' and isinstance(request_id, str) and 1 <= len(request_id) <= 160:
                return GloveControl(request_id)
            return None
        return original_decode(raw)
    module.decode_message = decode
    original_init = module.LowFreqServerManager.__init__
    @functools.wraps(original_init)
    def initialize(self, *args, **kwargs):
        original_dispatch = kwargs['message_dispatcher']
        async def dispatch(ws, msg, addr):
            if isinstance(msg, McapCancel):
                from mcap_bridge import request_cancel
                request_cancel()
                self.logger.info('LinkerHand MCAP cancel requested')
                return
            if isinstance(msg, GloveControl):
                try:
                    result = await asyncio.to_thread(send_toggle, msg.request_id)
                except Exception:
                    self.logger.error('LinkerHand glove manager request failed:\n' + traceback.format_exc())
                else:
                    self.logger.info(f'LinkerHand X request {msg.request_id}: {result}')
                return
            return await original_dispatch(ws, msg, addr)
        kwargs['message_dispatcher'] = dispatch
        original_init(self, *args, **kwargs)
    module.LowFreqServerManager.__init__ = initialize
    print('LINKERHAND_VR_GLOVE_PATCH low-frequency X control enabled', flush=True)


def patch_web(module):
    original = module.WebServer._serve_file
    assets = {
        'input/gestureRecognizer.js': HERE/'frontend/gestureRecognizer.js',
        'utils/recordState.js': HERE/'frontend/recordState.js',
        'MessageToast.js': HERE/'frontend/MessageToast.js',
    }
    @functools.wraps(original)
    def serve(self, file_path, method, start_response):
        path = Path(file_path).resolve()
        root = Path('/home/dexforce/w1/dexe_teleoperate/src/frontend')
        relative = str(path.relative_to(root)) if path.is_relative_to(root) else ''
        asset = assets.get(relative)
        if asset is not None:
            body = asset.read_bytes()
            start_response('200 OK', [('Content-Type', 'application/javascript; charset=utf-8'),
                ('Content-Length', str(len(body))), ('Cache-Control', 'no-store')])
            return [] if method == 'HEAD' else [body]
        return original(self, file_path, method, start_response)
    module.WebServer._serve_file = serve
    print('LINKERHAND_VR_GLOVE_PATCH X short-press asset overlay enabled', flush=True)


def patch_module(name, module):
    if name == 'src.backend.pose.low_freq_server':
        patch_low_frequency(module)
    elif name in ('backend.web', 'src.backend.web'):
        patch_web(module)
    elif name == 'src.backend.recording.button_controller':
        from mcap_bridge import patch_buttons
        patch_buttons(module)
    elif name == 'src.backend.pose.message_handlers':
        from mcap_bridge import patch_handlers
        patch_handlers(module)
