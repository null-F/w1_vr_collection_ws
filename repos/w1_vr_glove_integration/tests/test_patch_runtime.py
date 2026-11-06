"""Exercise the X dispatcher without calling the physical glove manager."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import patch_runtime


class VendorLogger:
    """The vendor API accepts extra metadata, not logging's *args."""

    def __init__(self):
        self.messages = []

    def info(self, msg, extra=None, **kwargs):
        self.messages.append(('info', msg))

    def error(self, msg, extra=None, **kwargs):
        self.messages.append(('error', msg))


def make_server():
    forwarded = []

    class Server:
        def __init__(self, *, message_dispatcher):
            self.logger = VendorLogger()
            self.dispatch = message_dispatcher

    async def original_dispatch(ws, msg, addr):
        forwarded.append(msg)

    module = SimpleNamespace(LowFreqServerManager=Server, decode_message=lambda msg: msg)
    patch_runtime.patch_low_frequency(module)
    return Server(message_dispatcher=original_dispatch), forwarded


@pytest.mark.parametrize('failure', [None, URLError('manager unavailable'), TimeoutError('timed out')])
def test_x_request_keeps_dispatcher_usable_without_retry(failure):
    server, forwarded = make_server()
    request = patch_runtime.GloveControl('x-test-request')
    next_message = object()

    async def receive_messages():
        await server.dispatch(None, request, None)
        await server.dispatch(None, next_message, None)

    # Only the HTTP boundary is replaced; no robot control or network access.
    with patch.object(patch_runtime, 'send_toggle', return_value={'phase': 'starting'},
                      side_effect=failure) as toggle:
        asyncio.run(receive_messages())

    toggle.assert_called_once_with('x-test-request')
    assert forwarded == [next_message]
    level, message = server.logger.messages[-1]
    if failure is None:
        assert level == 'info'
        assert 'x-test-request' in message and 'starting' in message
    else:
        assert level == 'error'
        assert str(failure) in message and 'Traceback' in message
