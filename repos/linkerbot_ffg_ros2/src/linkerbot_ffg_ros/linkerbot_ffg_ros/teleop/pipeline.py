"""单手:读手套 → map → sink.publish。可选并行力反馈。"""

from __future__ import annotations

import time
from typing import Optional

from ..glove_ffg.reader import GloveReader
from ..teleop.types import JointCommand
from .force_reactor import ForceReactor

# 最后一帧有效关节之后，继续重发上一指令的最长时间。
LOST_HOLD_SEC = 1.0


class HandPipeline:
    def __init__(
        self,
        reader: GloveReader,
        mapper,
        sink,
        force_reactor: Optional[ForceReactor] = None,
        logger=None,
    ) -> None:
        self.reader = reader
        self.mapper = mapper
        self.sink = sink
        self.force_reactor = force_reactor
        self._logger = logger
        self._last_cmd: Optional[JointCommand] = None
        self._force_zeroed_on_loss = False
        self._lost_reported = False

    @property
    def last_cmd(self) -> Optional[JointCommand]:
        return self._last_cmd

    def _log(self, level: str, message: str) -> None:
        if self._logger is None:
            return
        log = getattr(self._logger, level, None)
        if log is not None:
            log(message)

    def _handle_lost_input(self) -> Optional[JointCommand]:
        # 截止时间 = 最后有效关节帧 + LOST_HOLD_SEC。
        if self._last_cmd is None:
            return None
        last = getattr(self.reader, "last_joint_mono", None)
        if last is None:
            return None
        now = time.monotonic()
        age = now - float(last)
        if not self._force_zeroed_on_loss:
            self._force_zeroed_on_loss = True
            if self.force_reactor is not None:
                self.force_reactor.zero()
        if age <= LOST_HOLD_SEC:
            self.sink.publish(self._last_cmd)
            return self._last_cmd
        if not self._lost_reported:
            self._lost_reported = True
            self._log("error", f"[{self.reader.side}] 手套失联")
        return None

    def tick(self, *, send_angle_query: bool = True) -> Optional[JointCommand]:
        self.reader.poll(send_angle_query=send_angle_query)
        frame = self.reader.read()
        if frame is None or not frame.valid:
            return self._handle_lost_input()
        if self._lost_reported:
            self._log("info", f"[{self.reader.side}] 手套已恢复")
        self._lost_reported = False
        self._force_zeroed_on_loss = False
        cmd = self.mapper.map(frame)
        self.sink.publish(cmd)
        self._last_cmd = cmd
        if self.force_reactor is not None:
            self.force_reactor.tick()
        return cmd
