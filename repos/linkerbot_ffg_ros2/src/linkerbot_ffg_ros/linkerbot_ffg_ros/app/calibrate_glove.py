#!/usr/bin/env python3
"""手套标定：扫口后左右手同时做同一动作采集。"""

from __future__ import annotations

import argparse
import glob
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from linkerbot_ffg_ros.calibration import (
    POSES,
    build_document,
    compute_base_vector,
    compute_joint_range_vector,
    new_calibration_stamp,
    prune_old_calibrations,
    save_calibration,
)
from linkerbot_ffg_ros.calibration.capture import (
    DEFAULT_HZ,
    DEFAULT_PREP_SECONDS,
    DEFAULT_STABLE_SECONDS,
    DEFAULT_THRESHOLD,
    DEFAULT_WINDOW,
    capture_pose_multi,
)
from linkerbot_ffg_ros.glove_ffg import GloveReader
from linkerbot_ffg_ros.glove_ffg.constants import DEFAULT_BAUDRATES

PORT_GLOBS = (
    "/dev/ttyUSB*",
    "/dev/ttyACM*",
    "/dev/ttyXRUSB*",
    "/dev/ttyOBC*",
)
FALLBACK_PORTS = ("/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0", "/dev/ttyACM1")

HandConn = Tuple[GloveReader, str, int]


# ANSI 颜色（不依赖 colorama）
_RESET = "\033[0m"
_BOLD = "\033[1m"
_RED = "\033[91m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_MAGENTA = "\033[95m"
_DIM = "\033[2m"
_BG_RED = "\033[41m"
_WHITE = "\033[97m"


def _c(color: str, text: str) -> str:
    return f"{color}{text}{_RESET}"


def _print_pose_prompt(index: int, total: int, pose) -> None:
    line = "━" * 56
    print()
    print(_c(_RED + _BOLD, line))
    title = f"【双手同时 {index}/{total}】{pose.label} ({pose.key})"
    print(_c(_RED + _BOLD, title))
    print(_c(_RED + _BOLD, f"  ▶ 请双手一起做：{pose.instruction}"))
    print(_c(_RED + _BOLD, line))


def _progress(frac, variance, drift, status: str) -> None:
    bar_len = 36
    filled = max(0, min(bar_len, int(round(bar_len * frac))))
    empty = bar_len - filled

    if status == "stable":
        color = _GREEN
        label = "稳定中"
        head = "█"
        tail = "░"
    elif status == "unstable":
        color = _YELLOW
        label = "等待稳定"
        head = "█"
        tail = "░"
    elif status.startswith("warming"):
        color = _CYAN
        label = f"预热 {status.split()[-1] if ' ' in status else status}"
        head = "▓"
        tail = "░"
    else:
        color = _MAGENTA
        label = "等待数据"
        head = "▓"
        tail = "░"

    bar = head * filled + tail * empty
    pct = f"{frac * 100:5.1f}%"
    if variance is None:
        detail = f"{_DIM}var=-  drift=-{_RESET}"
    else:
        detail = f"{_DIM}var={variance:.4f}  drift={drift:.4f}{_RESET}"

    msg = (
        f"\r{_BOLD}{color}┃{bar}┃{_RESET} "
        f"{_BOLD}{color}{pct}{_RESET}  "
        f"{_BOLD}{color}{label:<8}{_RESET}  {detail}    "
    )
    print(msg, end="", flush=True)


def list_candidate_ports(port: Optional[str] = None) -> List[str]:
    if port:
        return [port]
    found: List[str] = []
    for pattern in PORT_GLOBS:
        found.extend(sorted(glob.glob(pattern)))
    if not found:
        for p in FALLBACK_PORTS:
            if Path(p).exists():
                found.append(p)
    seen = set()
    ports: List[str] = []
    for p in found:
        if p not in seen:
            seen.add(p)
            ports.append(p)
    return ports


def explicit_serial_targets(serial_spec) -> List[Tuple[str, int]]:
    """auto_scan 为 false 时，只返回配置里的左右串口。"""
    targets: List[Tuple[str, int]] = []
    seen: set[str] = set()
    for port, baud in (
        (serial_spec.left_port, serial_spec.left_baud),
        (serial_spec.right_port, serial_spec.right_baud),
    ):
        if not port or port in seen:
            continue
        seen.add(port)
        targets.append((str(port), int(baud)))
    if not targets:
        raise RuntimeError(
            "serial.auto_scan 为 false，但未配置 left.port 或 right.port"
        )
    return targets


def _try_glove(
    found: Dict[str, HandConn],
    used_ports: set[str],
    port: str,
    baud: int,
) -> None:
    if port in used_ports or ("left" in found and "right" in found):
        return
    reader = GloveReader()
    if not reader.open(port, baud):
        print(f"  打开失败: {port}@{baud}")
        return
    if not reader.query_version():
        print(f"  版本失败: {port}@{baud}")
        reader.close()
        return
    side = reader.side or "unknown"
    if side in found:
        print(f"  跳过 {port}@{baud}: side={side} 已占用")
        reader.close()
        return
    print(f"  发现 {port} baud={baud} -> side={side} version={reader.version}")
    found[side] = (reader, port, baud)
    used_ports.add(port)


def scan_gloves(
    port: Optional[str] = None,
    baud: Optional[int] = None,
    serial_spec=None,
) -> Dict[str, HandConn]:
    found: Dict[str, HandConn] = {}
    used_ports: set[str] = set()
    if serial_spec is not None and not serial_spec.auto_scan:
        targets = explicit_serial_targets(serial_spec)
        print(
            "固定串口: "
            + ", ".join(f"{item_port}@{item_baud}" for item_port, item_baud in targets)
        )
        for item_port, item_baud in targets:
            _try_glove(found, used_ports, item_port, item_baud)
    else:
        ports = list_candidate_ports(port)
        if serial_spec is not None and baud is None:
            bauds = list(serial_spec.baudrates)
        else:
            bauds = [baud] if baud is not None else list(DEFAULT_BAUDRATES)
        if not ports:
            raise RuntimeError("未发现候选串口，请指定 --port /dev/ttyUSB0")
        print(f"候选串口 ({len(ports)}): {', '.join(ports)}")
        print(f"尝试波特率: {bauds}")
        for item_baud in bauds:
            for item_port in ports:
                _try_glove(found, used_ports, item_port, item_baud)
                if "left" in found and "right" in found:
                    break
            if "left" in found and "right" in found:
                break

    if not found:
        raise RuntimeError("未发现可用手套")
    return found


def warmup_all(readers: Dict[str, GloveReader], seconds: float = 1.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        ready = True
        for r in readers.values():
            r.poll()
            if r.read() is None:
                ready = False
        if ready:
            break
        time.sleep(1.0 / DEFAULT_HZ)


def countdown_prep(seconds: float) -> None:
    end = time.time() + max(0.0, seconds)
    while True:
        remain = end - time.time()
        if remain <= 0:
            break
        show = max(1, int(remain + 0.999))
        print(
            f"\r{_RED}{_BOLD}⏱  {show} 秒后开始采集…请保持姿势{_RESET}   ",
            end="",
            flush=True,
        )
        time.sleep(min(0.2, remain))
    print(f"\r{_GREEN}{_BOLD}▶ 开始采集！请保持双手稳定{_RESET}                ")


def resolve_out_path(
    output: Optional[Path],
    side: str,
    *,
    stamp: Optional[str] = None,
) -> Optional[Path]:
    """None 表示交给 save_calibration 用默认目录+stamp；有 -o 则解析具体路径。"""
    if output is None:
        return None
    # 已存在目录、以 / 结尾、或无后缀路径 → 都当目录
    if output.is_dir() or str(output).endswith("/") or output.suffix == "":
        name = f"glove_{side}_{stamp}.yaml" if stamp else f"glove_{side}.yaml"
        return Path(output) / name
    if "{side}" in str(output):
        return Path(str(output).format(side=side))
    return output.with_name(f"{output.stem}_{side}{output.suffix}")


def run_calibration(
    gloves: Dict[str, HandConn],
    *,
    output: Optional[Path] = None,
    window: int = DEFAULT_WINDOW,
    threshold: float = DEFAULT_THRESHOLD,
    stable_seconds: float = DEFAULT_STABLE_SECONDS,
    prep_seconds: float = DEFAULT_PREP_SECONDS,
    hz: float = DEFAULT_HZ,
    close_on_exit: bool = True,
) -> Dict[str, Path]:
    """对已打开的手套做五态采集并保存。

    Args:
        gloves: scan_gloves() 的返回值。
        output: 输出路径/目录；None 用默认 calibration 目录。
        close_on_exit: True 时结束关闭串口；teleop 复用手套时应传 False。

    Returns:
        {side: 标定文件 Path}
    """
    if not gloves:
        raise ValueError("gloves 为空，无法标定")

    order = [s for s in ("left", "right") if s in gloves]
    order.extend(sorted(s for s in gloves if s not in order))
    readers = {side: gloves[side][0] for side in order}

    print("\n" + "-" * 56)
    print(f"共发现 {len(gloves)} 只手套，将同时采集: "
          + ", ".join(f"{s}@{gloves[s][1]}" for s in order))
    print("-" * 56)

    print("预热读取角度…")
    warmup_all(readers)

    all_results: Dict[str, Dict[str, List[float]]] = {s: {} for s in order}
    saved_by_side: Dict[str, Path] = {}

    try:
        for i, pose in enumerate(POSES, start=1):
            _print_pose_prompt(i, len(POSES), pose)
            countdown_prep(prep_seconds)

            joints_by_side = capture_pose_multi(
                readers,
                pose,
                window=window,
                threshold=threshold,
                stable_seconds=stable_seconds,
                hz=hz,
                progress_callback=_progress,
            )
            print()
            print(_c(_GREEN + _BOLD, f"✔ 动作完成：{pose.label}"))
            for side, joints in joints_by_side.items():
                all_results[side][pose.key] = joints
                preview = [round(x, 3) for x in joints[:5]]
                print(_c(_GREEN, f"  ✔ [{side}] {pose.key}: first5={preview}"))

        stamp = new_calibration_stamp()
        saved: List[Path] = []
        capture_params = {
            "stability_window": window,
            "stability_threshold": threshold,
            "stable_seconds": stable_seconds,
            "prep_seconds": prep_seconds,
            "sample_hz": hz,
            "aggregate": "weighted_mean",
            "mode": "simultaneous",
        }
        for side in order:
            reader, port, baud = gloves[side]
            joint_range = None
            base = None
            glove_max = None
            try:
                joint_range = compute_joint_range_vector(all_results[side])
                base = compute_base_vector(all_results[side])
                glove_max = [base[i] + joint_range[i] for i in range(len(base))]
            except KeyError as exc:
                print(_c(
                    _YELLOW,
                    f"[{side}] 活动范围先不算（{exc}）。姿态已保存，ranges 规则待定。",
                ))
            else:
                print(_c(_CYAN + _BOLD, f"\n[{side}] 五指并拢 base (21):"))
                print(_c(_CYAN, "  " + ", ".join(f"{x:.4f}" for x in base)))
                print(_c(_CYAN + _BOLD, f"[{side}] ranges joint_range (21):"))
                print(_c(_CYAN, "  " + ", ".join(f"{x:.4f}" for x in joint_range)))
                print(_c(_CYAN + _BOLD, f"[{side}] 手套最大值 base+ranges (21):"))
                print(_c(_CYAN, "  " + ", ".join(f"{x:.4f}" for x in glove_max)))
            doc = build_document(
                side=side,
                glove_version=reader.version,
                port=port,
                baudrate=baud,
                poses=all_results[side],
                pose_defs=list(POSES),
                capture_params=capture_params,
                joint_range=joint_range,
                base=base,
                glove_max=glove_max,
            )
            path = save_calibration(
                doc,
                resolve_out_path(output, side, stamp=stamp),
                stamp=stamp,
            )
            saved.append(path)
            saved_by_side[side] = path
            print(f"[{side}] 已保存: {path}")

        removed = prune_old_calibrations(saved)
        if removed:
            print(
                _c(
                    _YELLOW,
                    f"已清理本轮标定侧别的旧文件 {len(removed)} 个（未标定的一侧保留）",
                )
            )
            for p in removed:
                print(_c(_YELLOW, f"  - 删除 {p.name}"))

        print("\n全部完成，当前保留:")
        for p in saved:
            print(f"  - {p}")
        return saved_by_side
    finally:
        if close_on_exit:
            for side in order:
                try:
                    gloves[side][0].close()
                except Exception:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="FFG 手套标定：左右手同时做动作，提示后自动倒计时采集"
    )
    parser.add_argument("--port", default=None)
    parser.add_argument("--baud", type=int, default=None)
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--stable-seconds", type=float, default=DEFAULT_STABLE_SECONDS)
    parser.add_argument("--prep-seconds", type=float, default=DEFAULT_PREP_SECONDS,
                        help="发出动作指令后等待多少秒再开始采集（默认 3）")
    parser.add_argument("--hz", type=float, default=DEFAULT_HZ)
    parser.add_argument("-o", "--output", default=None)
    parser.add_argument(
        "--config",
        default=None,
        help="YAML 路径。不传则使用 share/linkerbot_ffg_ros/config/default.yaml",
    )
    from linkerbot_ffg_ros.app.ros_args import non_ros_args

    args = parser.parse_args(non_ros_args())

    from linkerbot_ffg_ros.settings import load_yaml, resolve_settings

    try:
        settings = resolve_settings(
            load_yaml(Path(args.config) if args.config else None),
            cli_port=args.port,
            cli_baud=args.baud,
        )
    except ValueError as e:
        raise SystemExit(str(e)) from e
    gloves = scan_gloves(args.port, args.baud, serial_spec=settings.serial)
    try:
        run_calibration(
            gloves,
            output=Path(args.output) if args.output else None,
            window=args.window,
            threshold=args.threshold,
            stable_seconds=args.stable_seconds,
            prep_seconds=args.prep_seconds,
            hz=args.hz,
            close_on_exit=True,
        )
        return 0
    except KeyboardInterrupt:
        print("\n已取消标定")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
