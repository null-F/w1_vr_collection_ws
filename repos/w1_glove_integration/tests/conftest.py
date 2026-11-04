from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
for path in (
    ROOT / 'repos/w1_glove_integration',
    ROOT / 'repos/w1_vr_glove_integration',
    ROOT / 'repos/linkerbot_ffg_ros2/src/linkerbot_ffg_ros',
):
    sys.path.insert(0, str(path))
