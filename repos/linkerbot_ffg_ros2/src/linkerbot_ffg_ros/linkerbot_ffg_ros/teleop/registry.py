"""型号只登记一次。Mapper 文件末尾调用 register_mapper。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple, Type


@dataclass(frozen=True)
class MapperSpec:
    cls: Type
    n_in: int
    n_out: int
    kind: str


_SPECS: Dict[str, MapperSpec] = {}
_INCOMING: Dict[str, str] = {}
_LOADED = False


def _canon_key(raw: str) -> str:
    return (raw or "").strip().lower().replace(" ", "")


def register_mapper(
    cls: Type,
    *,
    aliases: Sequence[str] = (),
    incoming: Optional[Mapping[str, str]] = None,
    n_in: int,
    n_out: int,
    kind: str,
) -> None:
    """登记一个型号。aliases 是仍可直接使用的名字，incoming 是驱动上报名。"""
    if kind not in ("identity", "o30", "l20"):
        raise ValueError(f"未知 remap 种类: {kind!r}")
    name = _canon_key(str(cls.robot_name))
    if not name:
        raise ValueError(f"{cls.__name__} 缺少 robot_name")
    spec = MapperSpec(cls=cls, n_in=int(n_in), n_out=int(n_out), kind=kind)
    keys = [name, *[_canon_key(alias) for alias in aliases]]
    for key in keys:
        if not key:
            raise ValueError("型号名不能为空")
        if key in _SPECS or key in _INCOMING:
            raise ValueError(f"型号重复登记: {key}")
        _SPECS[key] = spec
    for raw, target in (incoming or {}).items():
        src = _canon_key(raw)
        dst = _canon_key(target)
        if not src or not dst:
            raise ValueError("上报名和目标型号不能为空")
        if src in _SPECS or src in _INCOMING:
            raise ValueError(f"型号重复登记: {src}")
        if dst not in _SPECS:
            raise ValueError(f"上报名 {src} 的目标 {dst} 尚未登记")
        _INCOMING[src] = dst


def ensure_mappers_loaded() -> None:
    """导入各 Mapper，触发它们末尾的 register_mapper。"""
    global _LOADED
    if _LOADED:
        return
    from ..mappers.l10 import L10Mapper  # noqa: F401
    from ..mappers.l20 import L20Mapper  # noqa: F401
    from ..mappers.l6 import L6Mapper  # noqa: F401
    from ..mappers.o30 import O30Mapper  # noqa: F401
    from ..mappers.o6 import O6Mapper  # noqa: F401

    _LOADED = True


def supported_robot_names() -> Tuple[str, ...]:
    ensure_mappers_loaded()
    return tuple(sorted(_SPECS))


def canonicalize_robot_name(raw: str) -> str:
    """把配置名、别名或驱动上报名收成登记名。别名保持原名，例如 l20lite。"""
    ensure_mappers_loaded()
    key = _canon_key(raw)
    if key in _SPECS:
        return key
    if key in _INCOMING:
        return _INCOMING[key]
    known = sorted([*_SPECS, *_INCOMING])
    raise ValueError(f"无法识别的手型号: {raw!r}，已支持: {known}")


def get_mapper_class(robot_name: str):
    """按已经归一的型号名取 Mapper 类。上报名要先经过 canonicalize_robot_name。"""
    ensure_mappers_loaded()
    key = _canon_key(robot_name)
    try:
        return _SPECS[key].cls
    except KeyError as e:
        raise KeyError(
            f"未支持的 robot: {robot_name!r}，可选: {sorted(_SPECS)}"
        ) from e


def mapper_spec(robot_name: str) -> MapperSpec:
    """按已经归一的型号名取输入输出长度和 remap 种类。"""
    ensure_mappers_loaded()
    key = _canon_key(robot_name)
    try:
        return _SPECS[key]
    except KeyError as e:
        raise KeyError(
            f"未知 robot 无法 remap 到 LinkerZ: {robot_name!r}，可选: {sorted(_SPECS)}"
        ) from e
