#!/usr/bin/env python3
"""手套遥操:O6/L6/L10/O30/L20 → LinkerH 或 LinkerZ,可选力反馈。

出口由 yaml.system.hand_sdk 选择:
  LinkerH → /cb_{left|right}_hand_control_cmd
  LinkerZ → 各手部节点的 /command/angles (RAW)

LinkerZ 力反馈:
  先订 force_fns、force_fn、normal_force_resultant。
  按 fns、fn、resultant 选定一次，之后只保留这一路。

标定:
  默认每次遥操先现场标定(复用已打开的手套串口)。
  --skip-calibrate 可跳过,改用 calib_dir 里最新标定文件。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _parse_force_max(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        val = int(raw)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"--force-feedback 后必须是整数,got {raw!r}") from e
    if val < 0:
        raise argparse.ArgumentTypeError(f"--force-feedback 值不可为负: {val}")
    return val


def _wait_until(node, deadline: float) -> float:
    """处理回调直到截止时间。本轮已经超时则把截止时间重置为现在。"""
    import rclpy

    now = time.monotonic()
    if now >= deadline:
        return now
    while rclpy.ok():
        remain = deadline - time.monotonic()
        if remain <= 0:
            return deadline
        rclpy.spin_once(node, timeout_sec=remain)
    return time.monotonic()


def _build_parser() -> argparse.ArgumentParser:
    from linkerbot_ffg_ros.teleop.registry import supported_robot_names

    p = argparse.ArgumentParser(
        description="LinkerForce 手套 → LinkerH(/cb_*) 或 LinkerZ(/linkerbot_hand/...)"
    )
    p.add_argument(
        "--config",
        default=None,
        help="YAML 路径。不传则使用 share/linkerbot_ffg_ros/config/default.yaml",
    )
    p.add_argument(
        "--robot",
        choices=("auto",) + supported_robot_names(),
        default=None,
        help="覆盖 yaml.system.robot；auto=按 hand_sdk 自动识别",
    )
    p.add_argument(
        "--hand-sdk",
        choices=("LinkerH", "LinkerZ"),
        default=None,
        help="覆盖 yaml.system.hand_sdk",
    )
    p.add_argument("--port", default=None, help="覆盖 yaml.serial 里的候选端口(两只手都试)")
    p.add_argument("--baud", type=int, default=None, help="覆盖 yaml.serial 里的候选波特率")
    p.add_argument("--rate", type=float, default=None, help="覆盖 yaml.teleop.rate_hz")
    p.add_argument("--calib-dir", default=None, help="覆盖 yaml.teleop.calib_dir")
    p.add_argument(
        "--skip-calibrate",
        action="store_true",
        help="跳过启动标定,使用 calib_dir 中最新标定文件",
    )
    p.add_argument("--print", action="store_true", help="终端打印电机值")
    p.add_argument("--no-smooth", action="store_true", help="关闭电机平滑(覆盖 yaml)")
    p.add_argument("--smooth-alpha", type=float, default=None)
    p.add_argument("--smooth-max-step", type=float, default=None)

    fb = p.add_mutually_exclusive_group()
    fb.add_argument(
        "-F", "--force-feedback",
        nargs="?", const="__on__", default=None,
        metavar="MAX",
        help="强制开力反馈;可选跟 max_force(0..hardware_limit)。例:-F / -F 1000",
    )
    fb.add_argument(
        "--no-force-feedback",
        action="store_true",
        help="强制关力反馈(覆盖 yaml)",
    )
    return p


def _cli_force_triple(args) -> tuple[str | None, int | None]:
    if args.no_force_feedback:
        return "off", None
    if args.force_feedback is None:
        return None, None
    if args.force_feedback == "__on__":
        return "on", None
    return "on", _parse_force_max(args.force_feedback)


def _log_settings(node, settings) -> None:
    log = node.get_logger()
    log.info(
        f"robot={settings.robot}  hand_sdk={settings.hand_sdk}  "
        f"(robot_source: {settings.robot_source})  "
        f"rate={settings.rate_hz:.1f} Hz  "
        f"smooth={settings.smooth} (α={settings.smooth_alpha}, step={settings.smooth_max_step})"
    )
    log.info(f"calib_dir={settings.calib_dir}")
    if settings.hand_sdk == "LinkerZ":
        z = settings.linker_z
        log.info(
            f"linker_z topics left={z.topics.get('left')} right={z.topics.get('right')} "
            f"client_id={z.client_id} o30_swap_01={z.o30_swap_01}"
        )
    fb = settings.force
    if fb.enabled:
        log.info(
            f"force_feedback = ON   max_force={fb.max_force}  "
            f"[trigger={fb.trigger_mass} onset={fb.force_onset} mass_max={fb.mass_max} "
            f"hw_limit={fb.hardware_limit}]  (source: {fb.source})"
        )
    else:
        log.info(f"force_feedback = OFF   (source: {fb.source})")


_SIDE_NAME = {"left": "左手", "right": "右手"}


def _warn_driver_gaps(
    node,
    *,
    glove_sides,
    driver_sides,
    publish_unmatched: bool,
    topic_for,
) -> None:
    """手套和手驱动侧别不一致时警告。"""
    gloves = {side for side in glove_sides if side in _SIDE_NAME}
    drivers = {side for side in driver_sides if side in _SIDE_NAME}
    for side in ("left", "right"):
        name = _SIDE_NAME[side]
        topic = topic_for(side) or "(无话题)"
        if side in gloves and side not in drivers:
            if publish_unmatched:
                node.get_logger().warning(
                    f"[{side}] 没有{name}节点，{topic} 目前没有订阅者"
                )
            else:
                node.get_logger().warning(
                    f"[{side}] 没有{name}节点，{name}指令不发布，避免发到其他手的话题"
                )
        elif side in drivers and side not in gloves:
            node.get_logger().warning(
                f"[{side}] {name}驱动已启动，但没有{name}手套向 {topic} 发指令"
            )


def main() -> int:
    from linkerbot_ffg_ros.app.ros_args import non_ros_args

    args = _build_parser().parse_args(non_ros_args())

    try:
        import rclpy
        from rclpy.node import Node
    except ImportError as e:
        print("需要 ROS2 Python 环境(rclpy)。请先 source 对应 setup.bash", file=sys.stderr)
        raise SystemExit(1) from e

    from linkerbot_ffg_ros.settings import (
        apply_discovered_robot,
        load_yaml,
        resolve_settings,
    )
    from linkerbot_ffg_ros.app.calibrate_glove import run_calibration, scan_gloves
    from linkerbot_ffg_ros.calibration import find_latest_calibration, load_calibration
    from linkerbot_ffg_ros.detect import (
        collect_linker_h_payloads,
        linker_h_reported_sides,
        linker_h_robot_from_payloads,
        print_robot_discovery,
    )
    from linkerbot_ffg_ros.sinks.ros_joint_state import TOPIC_BY_SIDE
    from linkerbot_ffg_ros.sinks import create_hand_sink, sink_topic_for
    from linkerbot_ffg_ros.teleop.pipeline import HandPipeline
    from linkerbot_ffg_ros.teleop.force_reactor import ForceReactor
    from linkerbot_ffg_ros.teleop.registry import get_mapper_class
    from linkerbot_ffg_ros.force import TouchForceMapper

    yaml_doc = load_yaml(Path(args.config)) if args.config else load_yaml()
    cli_force, cli_force_max = _cli_force_triple(args)
    try:
        settings = resolve_settings(
            yaml_doc,
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
    except ValueError as e:
        raise SystemExit(str(e)) from e

    gloves = scan_gloves(args.port, args.baud, serial_spec=settings.serial)
    order = [s for s in ("left", "right") if s in gloves]
    order.extend(sorted(s for s in gloves if s not in order))

    node = None
    sink = None
    touch_source = None
    reactors: dict = {}
    ros_started = False

    try:
        # ---- 标定(默认每次启动都做;与遥操共用已打开的串口) ----
        if args.skip_calibrate:
            calib_paths = {
                side: find_latest_calibration(side, directory=settings.calib_dir)
                for side in order
            }
            print("已跳过标定,使用最新文件:")
            for side, path in calib_paths.items():
                print(f"  [{side}] {path}")
        else:
            print("\n>>> 遥操前先标定(可用 --skip-calibrate 跳过)\n")
            calib_paths = run_calibration(
                gloves,
                output=settings.calib_dir,
                close_on_exit=False,
            )
            missing = [s for s in order if s not in calib_paths]
            if missing:
                raise RuntimeError(f"标定未覆盖所有手套: missing={missing}")

        # ---- 标定结束后启动 ROS ----
        # 使用完整 sys.argv 初始化节点。
        rclpy.init()
        ros_started = True
        # 节点名先用占位；识别后再在日志里打真实 robot
        node = Node(f"linkerforce_{settings.robot}_teleop")

        # LinkerZ：只绑定有节点的手套侧。没有节点的一侧不发布。
        # LinkerH：每只手套仍发自己的 /cb_*_hand_control_cmd，缺驱动时只警告。
        command_sides = list(order)
        if settings.hand_sdk == "LinkerZ":
            from dataclasses import replace

            from linkerbot_ffg_ros.detect.linker_z_route import (
                bind_linker_z_routes,
                discover_linker_z_hands,
            )

            hands = discover_linker_z_hands(
                node,
                timeout_sec=settings.linker_z.discover_timeout_sec,
                extra_topics=(settings.linker_z.capabilities_topic,),
            )
            explicit = {
                side: topic
                for side, topic in settings.linker_z.topics.items()
                if topic
            }
            try:
                bound = bind_linker_z_routes(order, hands, explicit)
            except ValueError as e:
                raise SystemExit(str(e)) from e
            if bound.robot is not None and settings.robot not in ("auto", bound.robot):
                raise SystemExit(
                    f"配置 robot={settings.robot} 与手部节点型号 {bound.robot} 不一致"
                )
            topics = {"left": "", "right": ""}
            topics.update(bound.routes)
            settings = replace(
                settings,
                linker_z=replace(settings.linker_z, topics=topics),
            )
            command_sides = [side for side in order if side in bound.routes]
            if settings.robot == "auto" and bound.robot is not None:
                src = "LinkerZ " + ", ".join(
                    f"{side}={bound.routes[side]}" for side in command_sides
                )
                settings = apply_discovered_robot(
                    settings, yaml_doc, bound.robot,
                    source=src,
                    cli_force=cli_force,
                    cli_force_max=cli_force_max,
                )
                print_robot_discovery(
                    hand_sdk=settings.hand_sdk,
                    robot=settings.robot,
                    source=settings.robot_source,
                )
                node.get_logger().info(
                    f"手型识别 robot={settings.robot}  source={settings.robot_source}"
                )
            driver_topics = dict(bound.idle_topics)
            driver_topics.update(bound.routes)
            _warn_driver_gaps(
                node,
                glove_sides=order,
                driver_sides=driver_topics,
                publish_unmatched=False,
                topic_for=lambda side: driver_topics.get(side, ""),
            )
        else:
            got = collect_linker_h_payloads(node, timeout_sec=2.0)
            reported = linker_h_reported_sides(got)
            if settings.robot == "auto":
                try:
                    found = linker_h_robot_from_payloads(got, active_sides=order)
                except Exception as e:
                    raise SystemExit(
                        f"robot=auto ({settings.hand_sdk}) 识别失败: {e}"
                    ) from e
                settings = apply_discovered_robot(
                    settings, yaml_doc, found.robot,
                    source=found.source,
                    cli_force=cli_force,
                    cli_force_max=cli_force_max,
                )
                print_robot_discovery(
                    hand_sdk=settings.hand_sdk,
                    robot=settings.robot,
                    source=settings.robot_source,
                )
                node.get_logger().info(
                    f"手型识别 robot={settings.robot}  source={settings.robot_source}"
                )
                if found.borrowed_from:
                    names = "、".join(_SIDE_NAME[side] for side in found.borrowed_from)
                    node.get_logger().warning(
                        f"已连接手套没有 hand_info，型号 {found.robot} 来自{names}。"
                        "手套仍向自己的话题发指令，对侧驱动不会收到。"
                    )
            _warn_driver_gaps(
                node,
                glove_sides=order,
                driver_sides=reported,
                publish_unmatched=True,
                topic_for=lambda side: TOPIC_BY_SIDE.get(side, ""),
            )

        period = 1.0 / max(settings.rate_hz, 1.0)
        deadline = time.monotonic()
        if not command_sides:
            node.get_logger().warning("没有可控制的手，进程保持运行。Ctrl+C 退出")
            while rclpy.ok():
                rclpy.spin_once(node, timeout_sec=0.0)
                deadline += period
                deadline = _wait_until(node, deadline)
        else:
            if settings.robot == "auto":
                raise SystemExit("robot 仍为 auto，无法继续")

            try:
                MapperCls = get_mapper_class(settings.robot)
            except KeyError as e:
                raise SystemExit(str(e)) from e

            _log_settings(node, settings)

            try:
                sink = create_hand_sink(settings, node)
            except ImportError as e:
                raise SystemExit(
                    f"hand_sdk={settings.hand_sdk} 所需消息包未安装/未 source: {e}"
                ) from e

            if settings.force.enabled:
                from linkerbot_ffg_ros.sources import create_touch_source

                force_mapper = TouchForceMapper(settings.force)
                for side in command_sides:
                    reader, _, _ = gloves[side]
                    reactors[side] = ForceReactor(
                        reader, side, force_mapper, logger=node.get_logger()
                    )

                def _dispatch(touch):
                    r = reactors.get(touch.side)
                    if r is not None:
                        r.on_touch(touch)

                try:
                    touch_source = create_touch_source(
                        settings, node, _dispatch, sides=command_sides,
                    )
                except ImportError as e:
                    raise SystemExit(
                        f"力反馈输入依赖未安装/未 source (hand_sdk={settings.hand_sdk}): {e}"
                    ) from e

            pipelines = {}
            for side in command_sides:
                reader, port, baud = gloves[side]
                path = calib_paths[side]
                doc = load_calibration(path)
                mapper = MapperCls.from_calibration_doc(
                    doc,
                    side=side,
                    smooth=settings.smooth,
                    smooth_alpha=settings.smooth_alpha,
                    smooth_max_step=settings.smooth_max_step,
                )
                pipelines[side] = HandPipeline(
                    reader, mapper, sink,
                    force_reactor=reactors.get(side),
                    logger=node.get_logger(),
                )
                node.get_logger().info(
                    f"[{side}] robot={settings.robot} hand_sdk={settings.hand_sdk} "
                    f"calib={path.name} port={port} → {sink_topic_for(sink, side)} "
                    f"dims={len(mapper.joint_names)}"
                )

            node.get_logger().info(
                f"teleop {settings.robot}/{settings.hand_sdk} "
                f"@ {settings.rate_hz} Hz(Ctrl+C 退出)"
            )
            while rclpy.ok():
                rclpy.spin_once(node, timeout_sec=0.0)
                line_parts = []
                for side in command_sides:
                    cmd = pipelines[side].tick()
                    if args.print and cmd is not None:
                        preview = " ".join(f"{p:5.1f}" for p in cmd.positions[:8])
                        more = f" …(+{len(cmd.positions)-8})" if len(cmd.positions) > 8 else ""
                        line_parts.append(f"[{side}] {preview}{more}")
                if args.print and line_parts:
                    print("\r" + " | ".join(line_parts) + "     ", end="", flush=True)
                deadline += period
                deadline = _wait_until(node, deadline)
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        for r in reactors.values():
            try:
                r.zero()
            except Exception:
                pass
        if touch_source is not None:
            try:
                touch_source.close()
            except Exception:
                pass
        for reader, _, _ in gloves.values():
            try:
                reader.close()
            except Exception:
                pass
        if sink is not None:
            try:
                sink.close()
            except Exception:
                pass
        if node is not None:
            try:
                node.destroy_node()
            except Exception:
                pass
        if ros_started and rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
