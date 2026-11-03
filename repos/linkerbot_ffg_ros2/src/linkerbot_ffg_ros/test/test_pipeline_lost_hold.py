"""丢帧保持时间按最后有效物理帧计算，不再叠加 reader 缓存窗口。"""

from types import SimpleNamespace

import linkerbot_ffg_ros.teleop.pipeline as pipeline


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t


class _Reader:
    side = "left"
    last_joint_mono = 0.0  # 最后有效物理帧时间；允许为 0

    def poll(self, send_angle_query: bool = True) -> None:
        return None

    def read(self):
        # 与 GloveReader 一致：超过 0.5 秒不再返回缓存帧。
        if pipeline.time.monotonic() - float(self.last_joint_mono) > 0.5:
            return None
        return SimpleNamespace(valid=True, joints_deg=[0.0] * 21, side="left")


class _Sink:
    def __init__(self) -> None:
        self.times = []

    def publish(self, cmd) -> None:
        self.times.append(pipeline.time.monotonic())


class _Mapper:
    def map(self, frame):
        return SimpleNamespace(values=[1], side="left")


def test_stop_publish_one_second_after_last_physical_frame(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(pipeline.time, "monotonic", clock.monotonic)

    reader = _Reader()
    sink = _Sink()
    pl = pipeline.HandPipeline(reader, _Mapper(), sink)

    last_publish = None
    first_stop = None
    for _ in range(80):
        cmd = pl.tick(send_angle_query=False)
        if cmd is not None:
            last_publish = clock.t
        elif last_publish is not None and first_stop is None:
            first_stop = clock.t
            break
        clock.t = round(clock.t + 0.02, 10)

    assert last_publish == 1.0
    assert first_stop == 1.02
