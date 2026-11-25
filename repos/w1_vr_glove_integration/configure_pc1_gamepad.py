#!/usr/bin/env python3
"""Add an environment-controlled opt-out for PC1's two local gamepad nodes."""
import ast
from pathlib import Path

TARGET = Path('/home/dexforce/w1/install/mobile_joy_control/share/mobile_joy_control/launch/joy_only.launch.py')


def patch(source):
    ast.parse(source)
    for name in ('joy_node', 'mobile_joy_control_node'):
        original = f'    nodes.append({name})'
        replacement = f'    if os.environ.get("LINKERHAND_GAMEPAD_HOST", "pc1") != "pc2":\n        nodes.append({name})'
        if replacement in source:
            continue
        if source.count(original) != 1:
            raise ValueError('Unexpected vendor launch structure: '+name)
        source = source.replace(original, replacement)
    ast.parse(source)
    return source


if __name__ == '__main__':
    original = TARGET.read_text()
    changed = patch(original)
    backup = TARGET.with_name('joy_only.launch.py.before_pc2_gamepad')
    if changed != original:
        if not backup.exists():
            backup.write_text(original)
        TARGET.write_text(changed)
    print('PC1 gamepad launch configured; cmd_vel_mux and other nodes preserved')
