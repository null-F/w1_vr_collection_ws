"""各型号共用的电机输出平滑。"""

from __future__ import annotations

from typing import List, Sequence

DEFAULT_SMOOTH_ALPHA = 0.5
DEFAULT_SMOOTH_MAX_STEP = 20.0


class MotorSmoother:
    """电机输出平滑：指数移动平均 + 步长限制。"""

    def __init__(
        self,
        num_motors: int = 6,
        *,
        enabled: bool = True,
        alpha: float = DEFAULT_SMOOTH_ALPHA,
        max_step: float = DEFAULT_SMOOTH_MAX_STEP,
    ) -> None:
        self.num_motors = int(num_motors)
        self.enabled = bool(enabled)
        self.alpha = float(alpha)
        self.max_step = float(max_step)
        self._state: List[float] | None = None

    def reset(self, values: Sequence[float] | None = None) -> None:
        if values is None:
            self._state = None
            return
        if len(values) != self.num_motors:
            raise ValueError(f"values must be length {self.num_motors}")
        self._state = [float(x) for x in values]

    def apply(self, raw: Sequence[float]) -> List[float]:
        if len(raw) != self.num_motors:
            raise ValueError(f"raw must be length {self.num_motors}")
        raw_f = [float(x) for x in raw]
        if not self.enabled:
            return raw_f
        if self._state is None:
            self._state = list(raw_f)
            return list(raw_f)

        out: List[float] = []
        a = self.alpha
        for i, r in enumerate(raw_f):
            target = a * r + (1.0 - a) * self._state[i]
            diff = target - self._state[i]
            if abs(diff) > self.max_step:
                target = self._state[i] + (self.max_step if diff > 0 else -self.max_step)
            self._state[i] = target
            out.append(target)
        return out
