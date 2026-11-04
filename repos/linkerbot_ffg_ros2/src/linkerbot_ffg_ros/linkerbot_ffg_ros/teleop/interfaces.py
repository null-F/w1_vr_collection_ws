"""各层接口。"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from .types import ForceCommand, GloveFrame, JointCommand


@runtime_checkable
class GloveSource(Protocol):
    """手套输入源。"""

    def open(self, port: str, baudrate: int) -> bool: ...

    def close(self) -> None: ...

    def query_version(self) -> bool: ...
    #发一次角度查询、读一批字节、把解出来的帧塞到内部缓冲

    def poll(self, send_angle_query: bool = True) -> None: ...

    def read(self) -> Optional[GloveFrame]: ...

    def send_force(self, values: ForceCommand | list[float]) -> bool: ...

    @property
    def version(self) -> Optional[str]: ...

    @property
    def side(self) -> Optional[str]: ...

#手套数据怎么变成发送给手的数据
@runtime_checkable
class HandMapper(Protocol):
    """关节映射。"""

    robot_name: str

    def map(self, frame: GloveFrame) -> JointCommand: ...

    def reset(self) -> None: ...


@runtime_checkable
class HandSink(Protocol):
    """关节指令输出。"""

    def publish(self, cmd: JointCommand) -> None: ...

    def close(self) -> None: ...
