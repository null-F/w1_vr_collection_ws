"""标定采集：断流后必须重新稳定，不能沿用旧计时。"""

from types import SimpleNamespace

import linkerbot_ffg_ros.calibration.capture as capture


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t = round(self.t + float(dt), 10)


class _ScriptedReader:
    """按单调时钟返回帧；缺席的时刻表示断流。"""

    def __init__(self, valid_at, joints=None) -> None:
        self.is_open = True
        self._valid_at = {round(float(t), 10) for t in valid_at}
        self._joints = [0.0] * 21 if joints is None else list(joints)

    def poll(self) -> None:
        return None

    def read(self):
        if round(capture.time.monotonic(), 10) in self._valid_at:
            return SimpleNamespace(valid=True, joints_deg=list(self._joints))
        return None


def _patch_clock(monkeypatch, clock: _Clock) -> None:
    monkeypatch.setattr(capture.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(capture.time, "sleep", clock.sleep)


def test_gap_requires_full_restable_period(monkeypatch):
    clock = _Clock()
    _patch_clock(monkeypatch, clock)
    # 开头两帧启动计时，中间断约 10 秒；旧逻辑会在约 10.2 秒完成。
    valid = {0.0, 0.1} | {round(10.1 + 0.1 * i, 10) for i in range(60)}
    out = capture.capture_pose_multi(
        {"left": _ScriptedReader(valid)},
        SimpleNamespace(key="open"),
        window=1,
        threshold=1.0,
        stable_seconds=5.0,
        hz=10.0,
        tracked_joints=[0],
    )
    assert out["left"][0] == 0.0
    # 10.1 秒恢复后重新计时 5 秒；循环在 collected 刚到 5 后再 sleep 一次退出。
    assert clock.t == 15.2


def test_single_side_gap_resets_both_hands(monkeypatch):
    clock = _Clock()
    _patch_clock(monkeypatch, clock)
    # 左手全程有帧；右手在 0.5~5.0 秒断流。两侧都必须重新稳定满 5 秒。
    left_valid = {round(0.1 * i, 10) for i in range(120)}
    right_valid = {round(0.1 * i, 10) for i in range(120) if not (0.5 <= 0.1 * i < 5.0)}
    statuses = []

    capture.capture_pose_multi(
        {
            "left": _ScriptedReader(left_valid),
            "right": _ScriptedReader(right_valid),
        },
        SimpleNamespace(key="open"),
        window=1,
        threshold=1.0,
        stable_seconds=5.0,
        hz=10.0,
        tracked_joints=[0],
        progress_callback=lambda *args: statuses.append((round(clock.t, 1), args[3])),
    )

    assert any(status == "waiting_frame" for _, status in statuses)
    # 右手 5.0 秒恢复后再稳 5 秒，不会沿用断流前的累计时间。
    assert clock.t == 10.1
