"""O6 映射：GloveFrame → u[21] → 6 路电机 JointCommand（含平滑）。"""

from __future__ import annotations

from typing import List, Optional, Sequence

from ..calibration.normalize import GloveChangeEstimator
from ..hands import o6 as o6_spec
from ..teleop.types import GloveChangeFrame, GloveFrame, HandSide, JointCommand


class O6Mapper:
    """标定变化量 → O6 六电机（开=255，合=0）+ 可选平滑。"""

    robot_name: str = o6_spec.ROBOT_NAME

    def __init__(
        self,
        estimator: GloveChangeEstimator,
        *,
        side: Optional[HandSide] = None,
        motor_open: Optional[Sequence[float]] = None,
        motor_fist: Optional[Sequence[float]] = None,
        smooth: bool = True,
        smooth_alpha: float = o6_spec.DEFAULT_SMOOTH_ALPHA,
        smooth_max_step: float = o6_spec.DEFAULT_SMOOTH_MAX_STEP,
    ) -> None:
        self.estimator = estimator
        self.side: Optional[HandSide] = side or estimator.side
        self.joint_names: List[str] = list(o6_spec.JOINT_NAMES)
        self.motor_open = list(motor_open) if motor_open is not None else list(o6_spec.MOTOR_OPEN)
        self.motor_fist = list(motor_fist) if motor_fist is not None else list(o6_spec.MOTOR_FIST)
        self.smoother = o6_spec.MotorSmoother(
            o6_spec.NUM_MOTORS,
            enabled=smooth,
            alpha=smooth_alpha,
            max_step=smooth_max_step,
        )
        self._last_change: Optional[GloveChangeFrame] = None
        self._last_u_sel: List[float] = [0.0] * o6_spec.NUM_MOTORS
        self._last_motors_raw: List[float] = list(self.motor_open)
        self._last_motors: List[float] = list(self.motor_open)

    @classmethod
    def from_calibration_doc(
        cls,
        doc,
        *,
        side: Optional[HandSide] = None,
        smooth: bool = True,
        smooth_alpha: float = o6_spec.DEFAULT_SMOOTH_ALPHA,
        smooth_max_step: float = o6_spec.DEFAULT_SMOOTH_MAX_STEP,
    ) -> "O6Mapper":
        est = GloveChangeEstimator.from_calibration_doc(doc)
        return cls(
            est,
            side=side or est.side,
            smooth=smooth,
            smooth_alpha=smooth_alpha,
            smooth_max_step=smooth_max_step,
        )

    @property
    def last_change(self) -> Optional[GloveChangeFrame]:
        return self._last_change

    @property
    def last_u_sel(self) -> List[float]:
        return list(self._last_u_sel)

    @property
    def last_motors(self) -> List[float]:
        return list(self._last_motors)

    @property
    def last_motors_raw(self) -> List[float]:
        return list(self._last_motors_raw)

    def map_change(self, change: GloveChangeFrame) -> JointCommand:
        if self.side is not None and change.side != self.side:
            raise ValueError(f"side mismatch: mapper={self.side}, change={change.side}")

        u_sel = [float(change.u[i]) if change.active[i] else 0.0 for i in o6_spec.GLOVE_INDICES]
        motors = o6_spec.map_u_to_motors(
            change.u,
            change.active,
            motor_open=self.motor_open,
            motor_fist=self.motor_fist,
        )
        motors = [max(0.0, min(255.0, float(m))) for m in motors]
        self._last_motors_raw = list(motors)
        motors = self.smoother.apply(motors)
        motors = [max(0.0, min(255.0, float(m))) for m in motors]

        self._last_change = change
        self._last_u_sel = u_sel
        self._last_motors = motors

        ros_names = [f"joint{i + 1}" for i in range(len(motors))]
        return JointCommand(
            side=change.side,
            robot_name=self.robot_name,
            joint_names=ros_names,
            positions=motors,
            timestamp=change.timestamp,
        )

    def map(self, frame: GloveFrame) -> JointCommand:
        return self.map_change(self.estimator.estimate(frame))

    def reset(self) -> None:
        self._last_change = None
        self._last_u_sel = [0.0] * o6_spec.NUM_MOTORS
        self._last_motors_raw = list(self.motor_open)
        self._last_motors = list(self.motor_open)
        self.smoother.reset()


from ..teleop.registry import register_mapper

register_mapper(O6Mapper, n_in=6, n_out=6, kind="identity")
