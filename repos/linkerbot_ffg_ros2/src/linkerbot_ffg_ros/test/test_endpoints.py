"""锁住各型号在 u 为 0 和 1 时的电机端点。"""

import math

from linkerbot_ffg_ros.hands import l6, l10, l20, o6, o30


def _full(value):
    return [float(value)] * 21, [True] * 21


def test_o6_and_l6_endpoints_match():
    assert l6.GLOVE_INDICES == o6.GLOVE_INDICES == (4, 1, 8, 12, 16, 20)
    assert l6.MOTOR_OPEN == o6.MOTOR_OPEN
    assert l6.MOTOR_FIST == o6.MOTOR_FIST

    for value, expected in ((0.0, o6.MOTOR_OPEN), (1.0, o6.MOTOR_FIST)):
        u, active = _full(value)
        assert o6.map_u_to_motors(u, active) == list(expected)
        assert l6.map_u_to_motors(u, active) == list(expected)


def test_l10_endpoints():
    u0, active0 = _full(0.0)
    u1, active1 = _full(1.0)
    assert l10.map_u_to_motors(u0, active0) == list(l10.MOTOR_OPEN)
    assert l10.map_u_to_motors(u1, active1) == list(l10.MOTOR_CLOSED)


def test_l20_endpoints():
    u0, active0 = _full(0.0)
    u1, active1 = _full(1.0)
    assert l20.map_u_to_motors(u0, active0) == list(l20.MOTOR_OPEN)
    assert l20.map_u_to_motors(u1, active1) == list(l20.MOTOR_CLOSED)


def test_o30_output_stays_in_range():
    for value in (0.0, 1.0):
        u, active = _full(value)
        motors = o30.map_u_to_motors(u, active)
        assert len(motors) == 20
        assert all(math.isfinite(motor) and 0.0 <= motor <= 255.0 for motor in motors)
