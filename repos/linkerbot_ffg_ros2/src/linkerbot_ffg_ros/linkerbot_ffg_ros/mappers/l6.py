"""L6 映射。通道和电机数值与 O6 相同，发出去的型号名是 l6。"""

from __future__ import annotations

from .o6 import O6Mapper
from ..teleop.registry import register_mapper


class L6Mapper(O6Mapper):
    robot_name = "l6"


register_mapper(
    L6Mapper,
    incoming={"l6p": "l6"},
    n_in=6,
    n_out=6,
    kind="identity",
)
