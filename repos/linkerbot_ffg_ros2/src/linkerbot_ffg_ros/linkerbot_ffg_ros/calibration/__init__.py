"""手套活动范围标定（与机械手型号无关）。"""

from .capture import capture_pose, capture_pose_multi, stability_metrics, weighted_average
from .normalize import (
    GloveChangeEstimator,
    normalize_glove_change,
    scale_u_to_motor,
    scale_u_to_motor_vector,
)
from .poses import POSES, PoseDef
from .ranges import compute_base_vector, compute_joint_range_vector
from .store import (
    build_document,
    default_calibration_path,
    find_latest_calibration,
    load_calibration,
    new_calibration_stamp,
    prune_old_calibrations,
    save_calibration,
)

__all__ = [
    "POSES",
    "PoseDef",
    "capture_pose",
    "capture_pose_multi",
    "stability_metrics",
    "weighted_average",
    "normalize_glove_change",
    "GloveChangeEstimator",
    "scale_u_to_motor",
    "scale_u_to_motor_vector",
    "compute_joint_range_vector",
    "compute_base_vector",
    "build_document",
    "save_calibration",
    "load_calibration",
    "find_latest_calibration",
    "new_calibration_stamp",
    "default_calibration_path",
    "prune_old_calibrations",
]
