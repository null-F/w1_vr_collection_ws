"""设备/型号自动发现。"""

from .robot import (
    collect_linker_h_payloads,
    discover_robot,
    linker_h_reported_sides,
    linker_h_robot_from_payloads,
    normalize_robot_name,
    print_robot_discovery,
)

__all__ = [
    "collect_linker_h_payloads",
    "discover_robot",
    "linker_h_reported_sides",
    "linker_h_robot_from_payloads",
    "normalize_robot_name",
    "print_robot_discovery",
]
