#!/usr/bin/env python3
"""W1 MCAP recorder. Does not publish control commands and does not touch /home/dexforce/w1."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import rclpy
import yaml
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_srvs.srv import Trigger

DATA_ROOT = Path("/home/dexforce/collection_data")
STATE_PATH = Path("/home/dexforce/linkerhand/runtime/mcap_recorder_state.json")
QOS_PATH = Path(__file__).resolve().parent / "qos_overrides.yaml"

BODY_JOINTS = [
    "ANKLE", "KNEE", "BUTTOCK", "WAIST", "NECK1", "NECK2",
    "LEFT_J1", "LEFT_J2", "LEFT_J3", "LEFT_J4", "LEFT_J5", "LEFT_J6", "LEFT_J7",
    "RIGHT_J1", "RIGHT_J2", "RIGHT_J3", "RIGHT_J4", "RIGHT_J5", "RIGHT_J6", "RIGHT_J7",
]
HAND_JOINTS = [
    "T_MCP", "T_CMC_YAW", "IF_MCP_PITCH", "MF_MCP_PITCH", "RF_MCP_PITCH", "LF_MCP_PITCH",
]

BASE_TOPICS = [
    "/feedback/joint",
    "/control/joint_position",
    "/feedback/odom",
    "/imu/chassis",
    "/control/cmd_vel",
    "/feedback/ee/left",
    "/feedback/ee/right",
    "/linkerhand/glove/left/motor_cmd",
    "/linkerhand/glove/right/motor_cmd",
    "/linkerhand/w1/ee/left/command",
    "/linkerhand/w1/ee/right/command",
    "/camera/left_eye_resize",
    "/camera/right_eye_resize",
    "/camera/kfc_calib_data",
    "/camera_l/color/image_rect_raw",
    "/camera_r/color/image_rect_raw",
    "/camera_l/color/camera_info",
    "/camera_r/color/camera_info",
    "/camera_l/extrinsics/depth_to_color",
    "/camera_r/extrinsics/depth_to_color",
]
DEPTH_TOPICS = [
    "/camera_l/depth/image_rect_raw",
    "/camera_r/depth/image_rect_raw",
    "/camera_l/depth/camera_info",
    "/camera_r/depth/camera_info",
]
WARN_IF_ABSENT = [
    "/feedback/joint",
    "/feedback/ee/left",
    "/feedback/ee/right",
    "/feedback/odom",
    "/camera/left_eye_resize",
    "/camera/right_eye_resize",
    "/camera/kfc_calib_data",
    "/camera_l/color/camera_info",
    "/camera_r/color/camera_info",
    "/camera_l/extrinsics/depth_to_color",
    "/camera_r/extrinsics/depth_to_color",
]


def _sensor_qos() -> QoSProfile:
    return QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
        history=HistoryPolicy.KEEP_LAST,
        depth=5,
    )


def _reliable_qos(depth: int = 10) -> QoSProfile:
    return QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.VOLATILE,
        history=HistoryPolicy.KEEP_LAST,
        depth=depth,
    )


def _valid_task(name: str) -> bool:
    if not name or len(name) > 80:
        return False
    return all(c.isalnum() or c in "-_" for c in name)


def _next_episode(task_dir: Path) -> Path:
    raw = task_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    nums = []
    for child in raw.iterdir():
        if child.is_dir() and child.name.startswith("episode_"):
            tail = child.name.split("_", 1)[1]
            if tail.isdigit():
                nums.append(int(tail))
    nxt = (max(nums) + 1) if nums else 0
    return raw / f"episode_{nxt:06d}"


def _camera_info_dict(msg) -> dict:
    return {
        "width": int(msg.width),
        "height": int(msg.height),
        "distortion_model": str(msg.distortion_model),
        "K": [float(v) for v in msg.k],
        "D": [float(v) for v in msg.d],
    }


def _extrinsics_dict(msg) -> dict:
    return {
        "rotation": [float(v) for v in msg.rotation],
        "translation": [float(v) for v in msg.translation],
    }


class Recorder(Node):
    def __init__(self) -> None:
        super().__init__("w1_mcap_recorder")
        self.declare_parameter("task_name", "")
        self.declare_parameter("collect_depth", False)
        self._proc = None
        self._episode_dir: Path | None = None
        self._started_wall: float | None = None
        self._topics: list[str] = []
        self.create_service(Trigger, "~/start_recording", self._on_start)
        self.create_service(Trigger, "~/stop_recording", self._on_stop)
        self.create_service(Trigger, "~/cancel_recording", self._on_cancel)
        self.create_service(Trigger, "~/status", self._on_status)
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    def _fail(self, response, text: str):
        response.success = False
        response.message = text
        self.get_logger().error(text)
        return response

    def _ok(self, response, text: str):
        response.success = True
        response.message = text
        self.get_logger().info(text)
        return response

    def _on_status(self, _req, response):
        if self._proc is not None and self._proc.poll() is None:
            return self._ok(response, f"recording {self._episode_dir}")
        return self._ok(response, "idle")

    def _on_start(self, _req, response):
        if self._proc is not None and self._proc.poll() is None:
            return self._fail(response, f"already recording {self._episode_dir}")
        task = str(self.get_parameter("task_name").value).strip()
        if not _valid_task(task):
            return self._fail(response, "task_name must be 1-80 chars of letters, digits, _ or -")
        collect_depth = bool(self.get_parameter("collect_depth").value)
        topics = list(BASE_TOPICS)
        if collect_depth:
            topics.extend(DEPTH_TOPICS)

        warnings = []
        for topic in WARN_IF_ABSENT:
            count = len(self.get_publishers_info_by_topic(topic))
            if count == 0:
                warnings.append(f"{topic} has no publisher")
                self.get_logger().warn(warnings[-1])

        episode_dir = _next_episode(DATA_ROOT / task)
        episode_dir.mkdir(parents=True, exist_ok=False)
        bag_dir = episode_dir / "raw"
        device = self._snapshot_device_info(warnings, collect_depth)
        (episode_dir / "device_info.json").write_text(
            json.dumps(device, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        cmd = [
            "ros2", "bag", "record",
            "-s", "mcap",
            "-o", str(bag_dir),
            "--include-unpublished-topics",
            "--qos-profile-overrides-path", str(QOS_PATH),
            "--max-cache-size", "134217728",
            *topics,
        ]
        self.get_logger().info(" ".join(cmd))
        log_handle = open(episode_dir / "record.log", "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            start_new_session=True,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        time.sleep(1.0)
        if proc.poll() is not None:
            log_handle.close()
            log = (episode_dir / "record.log").read_text(encoding="utf-8", errors="replace")[-2000:]
            import shutil
            shutil.rmtree(episode_dir, ignore_errors=True)
            return self._fail(response, f"ros2 bag record exited {proc.returncode}: {log}")
        self._log_handle = log_handle
        self._proc = proc
        self._episode_dir = episode_dir
        self._started_wall = time.time()
        self._topics = topics
        STATE_PATH.write_text(json.dumps({
            "pid": proc.pid,
            "episode_dir": str(episode_dir),
            "topics": topics,
        }), encoding="utf-8")
        return self._ok(response, str(episode_dir))

    def _snapshot_device_info(self, warnings: list[str], collect_depth: bool) -> dict:
        got = {}
        try:
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "snapshot"],
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                got = json.loads(proc.stdout)
            elif proc.stderr:
                warnings.append(proc.stderr.strip()[-500:])
        except Exception as exc:
            warnings.append(f"calibration snapshot failed: {exc}")
        joints = got.get("joints") or BODY_JOINTS
        info_l = got.get("info_l")
        info_r = got.get("info_r")
        ext_l = got.get("ext_l")
        ext_r = got.get("ext_r")
        return {
            "device": {"id": "w1-pc1", "type": "Dexforce W1"},
            "arm": {
                "model": "W1",
                "joints": joints,
                "left_arm_dof": 7,
                "right_arm_dof": 7,
                "waist": ["WAIST"],
                "head": ["NECK1", "NECK2"],
                "legs": ["ANKLE", "KNEE", "BUTTOCK"],
            },
            "hand": {
                "model": "Linker_L6",
                "dof": 6,
                "joint_names": HAND_JOINTS,
                "command_range": [0, 100],
                "glove_command_range": [0, 255],
                "state_topics": ["/feedback/ee/left", "/feedback/ee/right"],
                "command_topics": ["/linkerhand/w1/ee/left/command", "/linkerhand/w1/ee/right/command"],
                "glove_topics": ["/linkerhand/glove/left/motor_cmd", "/linkerhand/glove/right/motor_cmd"],
            },
            "glove": {"model": "LinkerForce"},
            "cameras": {
                "head_left": {
                    "topic": "/camera/left_eye_resize",
                    "calib_topic": "/camera/kfc_calib_data",
                    "calib_raw": got.get("calib"),
                },
                "head_right": {"topic": "/camera/right_eye_resize"},
                "cam_left_wrist": {
                    "topic": "/camera_l/color/image_rect_raw",
                    "color": info_l,
                    "extrinsics_depth_to_color": ext_l,
                },
                "cam_right_wrist": {
                    "topic": "/camera_r/color/image_rect_raw",
                    "color": info_r,
                    "extrinsics_depth_to_color": ext_r,
                },
            },
            "d2c_extrinsics": {"left_wrist": ext_l, "right_wrist": ext_r},
            "collect_depth": collect_depth,
            "warnings": warnings,
        }

    def _stop_proc(self) -> int | None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return None if proc is None else proc.poll()
        try:
            os.killpg(proc.pid, signal.SIGINT)
        except ProcessLookupError:
            return proc.poll()
        deadline = time.time() + 20.0
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.2)
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)
        return proc.poll()

    def _write_recording_info(self) -> None:
        episode = self._episode_dir
        if episode is None:
            return
        meta_path = episode / "raw" / "metadata.yaml"
        info = {
            "recording_time": datetime.fromtimestamp(self._started_wall or time.time(), timezone.utc).isoformat(),
            "duration_sec": None,
            "total_messages": 0,
            "topics_summary": {},
            "topics_config": [],
            "compression": {"mode": "none", "format": ""},
            "storage_identifier": "mcap",
            "image_format": {
                "head_left": "sensor_msgs/msg/Image",
                "head_right": "sensor_msgs/msg/Image",
                "wrist_color": "sensor_msgs/msg/Image",
                "head_calib": "std_msgs/msg/String",
            },
        }
        if meta_path.exists():
            meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
            bag = meta.get("rosbag2_bagfile_information", meta)
            duration = bag.get("duration", {})
            nanos = duration.get("nanoseconds", 0) if isinstance(duration, dict) else 0
            info["duration_sec"] = nanos / 1e9
            info["total_messages"] = bag.get("message_count", 0)
            info["storage_identifier"] = bag.get("storage_identifier", "mcap")
            summary = {}
            config = []
            for item in bag.get("topics_with_message_count", []):
                topic_meta = item.get("topic_metadata", {})
                name = topic_meta.get("name")
                summary[name] = item.get("message_count", 0)
                config.append({
                    "name": name,
                    "type": topic_meta.get("type"),
                    "serialization_format": topic_meta.get("serialization_format"),
                    "offered_qos_profiles": topic_meta.get("offered_qos_profiles"),
                })
            info["topics_summary"] = summary
            info["topics_config"] = config
        else:
            info["error"] = "metadata.yaml missing; bag may not have closed cleanly"
        (episode / "recording_info.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _on_stop(self, _req, response):
        if self._proc is None or self._proc.poll() is not None:
            return self._fail(response, "not recording")
        code = self._stop_proc()
        self._write_recording_info()
        episode = self._episode_dir
        self._proc = None
        if STATE_PATH.exists():
            STATE_PATH.unlink()
        return self._ok(response, f"saved {episode} (bag exit {code})")

    def _on_cancel(self, _req, response):
        if self._proc is None or self._proc.poll() is not None:
            return self._fail(response, "not recording")
        episode = self._episode_dir
        self._stop_proc()
        self._proc = None
        if STATE_PATH.exists():
            STATE_PATH.unlink()
        if episode is not None and episode.exists():
            import shutil
            shutil.rmtree(episode)
        self._episode_dir = None
        return self._ok(response, f"discarded {episode}")


def snapshot_main() -> None:
    """Separate process so a service callback does not re-enter the executor."""
    from sensor_msgs.msg import CameraInfo, JointState
    from std_msgs.msg import String

    rclpy.init()
    node = rclpy.create_node("w1_mcap_snapshot")
    got = {}
    node.create_subscription(String, "/camera/kfc_calib_data", lambda m: got.setdefault("calib", m.data), _reliable_qos(2))
    node.create_subscription(JointState, "/feedback/joint", lambda m: got.setdefault("joints", list(m.name)), _reliable_qos())
    node.create_subscription(CameraInfo, "/camera_l/color/camera_info", lambda m: got.setdefault("info_l", _camera_info_dict(m)), _reliable_qos())
    node.create_subscription(CameraInfo, "/camera_r/color/camera_info", lambda m: got.setdefault("info_r", _camera_info_dict(m)), _reliable_qos())
    try:
        from realsense2_camera_msgs.msg import Extrinsics
        node.create_subscription(Extrinsics, "/camera_l/extrinsics/depth_to_color", lambda m: got.setdefault("ext_l", _extrinsics_dict(m)), _reliable_qos())
        node.create_subscription(Extrinsics, "/camera_r/extrinsics/depth_to_color", lambda m: got.setdefault("ext_r", _extrinsics_dict(m)), _reliable_qos())
    except Exception as exc:
        print(f"realsense Extrinsics import failed: {exc}", file=sys.stderr)
    deadline = time.time() + 2.0
    while time.time() < deadline and len(got) < 3:
        rclpy.spin_once(node, timeout_sec=0.1)
    print(json.dumps(got))
    node.destroy_node()
    rclpy.shutdown()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "snapshot":
        snapshot_main()
        return
    if len(sys.argv) > 1 and sys.argv[1] != "serve":
        raise SystemExit("run via record.sh or: recorder.py serve")
    rclpy.init()
    node = Recorder()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        if node._proc is not None and node._proc.poll() is None:
            node._stop_proc()
            node._write_recording_info()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
