"""单侧标定只清理该侧旧文件，不删对侧。"""

from pathlib import Path

from linkerbot_ffg_ros.calibration.store import prune_old_calibrations


def test_prune_left_keeps_right_history(tmp_path: Path):
    left_old = tmp_path / "glove_left_old.yaml"
    right_old = tmp_path / "glove_right_old.yaml"
    left_new = tmp_path / "glove_left_new.yaml"
    for path in (left_old, right_old, left_new):
        path.write_text("x\n", encoding="utf-8")

    removed = prune_old_calibrations([left_new])

    assert sorted(p.name for p in removed) == ["glove_left_old.yaml"]
    assert not left_old.exists()
    assert left_new.exists()
    assert right_old.exists()


def test_prune_both_sides_only_removes_each_side_old_files(tmp_path: Path):
    left_old = tmp_path / "glove_left_old.yaml"
    right_old = tmp_path / "glove_right_old.yaml"
    left_new = tmp_path / "glove_left_new.yaml"
    right_new = tmp_path / "glove_right_new.yaml"
    other = tmp_path / "notes.yaml"
    for path in (left_old, right_old, left_new, right_new, other):
        path.write_text("x\n", encoding="utf-8")

    removed = prune_old_calibrations([left_new, right_new])

    assert sorted(p.name for p in removed) == [
        "glove_left_old.yaml",
        "glove_right_old.yaml",
    ]
    assert left_new.exists()
    assert right_new.exists()
    assert other.exists()
