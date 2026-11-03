"""
负责力反馈的运行协调
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from ..force.touch_force_mapper import TouchForceMapper
from ..force.types import TouchMass
from ..teleop.interfaces import GloveSource
from ..teleop.types import ForceCommand, HandSide


TOUCH_DATA_TIMEOUT_SEC = 0.5
ZERO_ATTEMPTS = 3


class ForceReactor:

    def __init__(
        self,
        reader: GloveSource,
        side: HandSide,
        mapper: TouchForceMapper,
        *,
        logger=None,
    ) -> None:
        self.reader = reader
        self.side: HandSide = side
        self.mapper = mapper
        self._lock = threading.Lock()
        self._pending: Optional[TouchMass] = None
        self._last_touch_mono: Optional[float] = None
        self._logger = logger
        self._write_fail_count = 0

    # ---- 订阅侧调用 ----

    def on_touch(self, touch: TouchMass) -> None:
        if touch.side != self.side:
            return
        with self._lock:
            self._pending = touch
            self._last_touch_mono = time.monotonic()

    # ---- pipeline tick 侧调用 ----

    def tick(self) -> Optional[ForceCommand]:
        with self._lock:
            touch = self._pending
            last_touch_mono = self._last_touch_mono
        if touch is None:
            return None
        if (
            last_touch_mono is None
            or time.monotonic() - last_touch_mono > TOUCH_DATA_TIMEOUT_SEC
        ):
            # 触觉断流：清空上一帧并发送五指 0。
            with self._lock:
                self._pending = None
                self._last_touch_mono = None
            self.zero()
            return None
        try:
            cmd = self.mapper.map(touch)
        except Exception as e:  # noqa: BLE001
            if self._logger is not None:
                self._logger.error(f"[{self.side}] force map 失败: {e}")
            self.zero()
            with self._lock:
                self._pending = None
                self._last_touch_mono = None
            return None
        ok = False
        try:
            ok = self.reader.send_force(cmd)
        except Exception as e:  # noqa: BLE001
            if self._logger is not None:
                self._logger.error(f"[{self.side}] send_force 抛错: {e}")
            return None
        if not ok:
            self._write_fail_count += 1
            if self._logger is not None and self._write_fail_count % 30 == 1:
                self._logger.warn(
                    f"[{self.side}] send_force 返回 False (第 {self._write_fail_count} 次,"
                    f"手套可能已断联)"
                )
        return cmd

    # ---- 生命周期 ----

    def zero(self) -> bool:
        """发送五指 0。未写完时最多尝试 ZERO_ATTEMPTS 次。"""
        command = ForceCommand(side=self.side, values=[0.0] * 5)
        last_error: Optional[Exception] = None
        for _ in range(ZERO_ATTEMPTS):
            try:
                if self.reader.send_force(command):
                    return True
            except Exception as e:  # noqa: BLE001
                last_error = e
        if self._logger is not None:
            detail = f": {last_error}" if last_error is not None else ""
            self._logger.error(f"[{self.side}] 停止出力指令未写完{detail}")
        return False

    def reset(self) -> None:
        with self._lock:
            self._pending = None
            self._last_touch_mono = None
        self._write_fail_count = 0
