"""Loaded only by the owned systemd VR drop-in, never installed system-wide."""
import os
if os.environ.get('LINKERHAND_W1_GLOVE_PATCH') == '1':
    import importlib.abc
    import importlib.machinery
    from pathlib import Path
    import subprocess
    import sys
    from patch_runtime import patch_module

    ROOT = str(Path(__file__).resolve().parent)
    TARGETS = {'src.backend.pose.low_freq_server', 'backend.web', 'src.backend.web',
               'src.backend.recording.button_controller', 'src.backend.pose.message_handlers'}

    class Loader(importlib.abc.Loader):
        def __init__(self, name, original):
            self.name, self.original = name, original
        def create_module(self, spec):
            return self.original.create_module(spec) if hasattr(self.original, 'create_module') else None
        def exec_module(self, module):
            self.original.exec_module(module)
            patch_module(self.name, module)

    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname not in TARGETS:
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec and spec.loader:
                spec.loader = Loader(fullname, spec.loader)
            return spec

    sys.meta_path.insert(0, Finder())
    original_run = subprocess.run
    def run(*args, **kwargs):
        command = args[0] if args else kwargs.get('args')
        if isinstance(command, (tuple, list)) and 'gunicorn' in command and 'backend.web:app' in command:
            env = dict(kwargs.get('env') or os.environ)
            paths = env.get('PYTHONPATH', '').split(os.pathsep)
            env['PYTHONPATH'] = os.pathsep.join([ROOT] + [p for p in paths if p and p != ROOT])
            env['LINKERHAND_W1_GLOVE_PATCH'] = '1'
            kwargs['env'] = env
        return original_run(*args, **kwargs)
    subprocess.run = run
