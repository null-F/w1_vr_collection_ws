"""锁住标定归一化的两个端点和过小量程。"""

from linkerbot_ffg_ros.calibration.normalize import normalize_glove_change


def test_endpoints_and_inactive_channel():
    base = [10.0] * 21
    joint_range = [20.0] * 21
    joint_range[3] = 1e-4
    current = list(base)
    current[0] = base[0] + joint_range[0]

    u, active, _, _ = normalize_glove_change(current, base, joint_range)

    assert u[1] == 0.0
    assert active[1] is True
    assert u[0] == 1.0
    assert active[0] is True
    assert u[3] == 0.0
    assert active[3] is False
