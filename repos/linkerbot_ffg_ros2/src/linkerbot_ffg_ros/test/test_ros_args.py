"""入口参数拆分：ROS 参数不再打断启动，应用参数仍原样进入配置。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from linkerbot_ffg_ros.app.calibrate_glove import main as calibrate_main
from linkerbot_ffg_ros.app.ros_args import non_ros_args
from linkerbot_ffg_ros.app.teleop_node import _build_parser, _cli_force_triple, main
from linkerbot_ffg_ros.settings import load_yaml, resolve_settings

_CONFIG = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
_ROS = ["--ros-args", "-r", "__node:=linkerbot_ffg_teleop", "-p", "use_sim_time:=true"]


def _settings_from(argv: list[str]):
    args = _build_parser().parse_args(non_ros_args(argv))
    cli_force, cli_force_max = _cli_force_triple(args)
    return resolve_settings(
        load_yaml(_CONFIG),
        cli_robot=args.robot,
        cli_hand_sdk=args.hand_sdk,
        cli_force=cli_force,
        cli_force_max=cli_force_max,
        cli_rate=args.rate,
        cli_calib_dir=Path(args.calib_dir) if args.calib_dir else None,
        cli_port=args.port,
        cli_baud=args.baud,
        cli_no_smooth=args.no_smooth,
        cli_smooth_alpha=args.smooth_alpha,
        cli_smooth_max_step=args.smooth_max_step,
    )


def test_launch_args_parse_and_match_plain_cli():
    plain = [
        "teleop",
        "--config",
        str(_CONFIG),
        "--robot",
        "o6",
        "--hand-sdk",
        "LinkerZ",
        "--port",
        "/dev/ttyFAKE",
        "--rate",
        "25",
        "--no-force-feedback",
        "--no-smooth",
    ]
    with_ros = plain + _ROS
    assert non_ros_args(with_ros) == plain[1:]
    assert _settings_from(plain) == _settings_from(with_ros)


def test_unknown_app_argument_still_rejected():
    argv = ["teleop", "--robots", "o6", *_ROS]
    with pytest.raises(SystemExit) as caught:
        _build_parser().parse_args(non_ros_args(argv))
    assert caught.value.code == 2


def test_calibrate_keeps_its_own_arguments():
    argv = ["calibrate", "--port", "/dev/ttyFAKE", "--window", "12", "-o", "/tmp/out", *_ROS]
    assert non_ros_args(argv) == ["--port", "/dev/ttyFAKE", "--window", "12", "-o", "/tmp/out"]


@pytest.mark.parametrize("with_ros", [False, True])
def test_teleop_reaches_glove_scan_with_cli_port(monkeypatch, with_ros):
    seen = {}

    def stop_at_scan(port, baud, serial_spec=None):
        seen["port"] = port
        seen["baud"] = baud
        seen["left_port"] = serial_spec.left_port
        seen["right_port"] = serial_spec.right_port
        raise RuntimeError("stop-before-hardware")

    monkeypatch.setattr(
        "linkerbot_ffg_ros.app.calibrate_glove.scan_gloves",
        stop_at_scan,
    )
    argv = [
        "teleop",
        "--config",
        str(_CONFIG),
        "--robot",
        "o6",
        "--hand-sdk",
        "LinkerZ",
        "--port",
        "/dev/ttyFAKE",
        "--baud",
        "2000000",
        "--skip-calibrate",
    ]
    if with_ros:
        argv = argv + _ROS
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(RuntimeError, match="stop-before-hardware"):
        main()

    assert seen["port"] == "/dev/ttyFAKE"
    assert seen["baud"] == 2000000
    assert seen["left_port"] == "/dev/ttyFAKE"
    assert seen["right_port"] == "/dev/ttyFAKE"


def test_calibrate_main_parses_ros_args_before_scan(monkeypatch):
    seen = {}

    def stop_at_scan(port, baud, serial_spec=None):
        seen["port"] = port
        seen["baud"] = baud
        raise RuntimeError("stop-before-hardware")

    monkeypatch.setattr(
        "linkerbot_ffg_ros.app.calibrate_glove.scan_gloves",
        stop_at_scan,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "calibrate",
            "--config",
            str(_CONFIG),
            "--port",
            "/dev/ttyFAKE",
            "--baud",
            "460800",
            *_ROS,
        ],
    )

    with pytest.raises(RuntimeError, match="stop-before-hardware"):
        calibrate_main()

    assert seen == {"port": "/dev/ttyFAKE", "baud": 460800}
