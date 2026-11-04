# linkerbot-ffg-ros2

手套遥操：读 FFG 力反馈手套串口，映射到灵巧手关节指令，可选触觉力反馈。支持 **LinkerH**（`/cb_*`）与 **LinkerZ**（`/linkerbot_hand/*`）。

许可证是 Apache-2.0，见仓库根目录 [LICENSE](LICENSE)。手部驱动不在本仓库：LinkerH 用 `linker_hand_ros2_sdk`，LinkerZ 用 `linkerbot_hand_ros`。本仓库的 `linkerbot_hand_msgs` 目前是 `2.0.0`。

## 功能概览

| 能力 | 说明 |
|------|------|
| 支持型号 | `o6` / `l6` / `l10` / `l20lite` / `o30` / `l20`（`auto` 可自动识别；`l20lite` 与 `l10` 共用 `L10Mapper`） |
| 手部后端 | `LinkerH` → `/cb_*_hand_control_cmd`；`LinkerZ` → `/linkerbot_hand/command/angles`（RAW）。默认 yaml 为 `LinkerZ` |
| 标定 | 启动遥操默认现场标定。不指定目录时写到 `~/.local/share/linkerbot_ffg_ros/calibration` |
| 力反馈 | LinkerH 订矩阵触觉。LinkerZ 先订 `force_fns`、`force_fn`、`normal_force_resultant`，选定一次后只保留该路（驱动需 `force_hz>0`） |

## 目录结构

```
linkerbot-ffg-ros2/
├── scripts/                 # 可选 .sh，只 source 工作空间再调用 ros2 run
├── data/calibration/        # 格式样例，不参与默认标定
└── src/
    ├── linkerbot_hand_msgs/
    └── linkerbot_ffg_ros/
        ├── config/default.yaml
        ├── launch/teleop.launch.py
        └── linkerbot_ffg_ros/   # Python 包
```

## 环境要求

- ROS 2 **Jazzy**（`rclpy`、`sensor_msgs`、`std_msgs`、`ament_index_python`）
- Python 3.12+（与 Jazzy 一致）
- 手套串口设备（如 `/dev/ttyUSB*`）
- 手部驱动已启动：LinkerH 用 `linker_hand_ros2_sdk`；LinkerZ 用 `linkerbot_hand_ros`
- Python 依赖由 `rosdep` 安装：`python3-numpy`、`python3-yaml`、`python3-serial`。`requirements.txt` 只作没有 rosdep 时的参考

## 快速开始

### 1. 编译安装

在仓库根目录：

```bash
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

### 2. 接好设备

- 手套插在串口上。
- LinkerZ 手部驱动已经在运行。

### 3. 启动遥操

三选一。

`ros2 run`，用第 1 步已经 source 的终端：

```bash
ros2 run linkerbot_ffg_ros teleop
```

`ros2 launch`，同样用已经 source 的终端：

```bash
ros2 launch linkerbot_ffg_ros teleop.launch.py
```

`scripts/teleop.sh`，脚本自己 source Jazzy 和 `install/setup.bash`，再执行 `ros2 run`：

```bash
scripts/teleop.sh
```

## 跳过标定

`ros2 run`，用已经 source 的终端：

```bash
ros2 run linkerbot_ffg_ros teleop --skip-calibrate
```

`scripts/teleop.sh`，脚本自己 source 后再执行 `ros2 run`：

```bash
scripts/teleop.sh --skip-calibrate
```

## 只标定

`ros2 run`，用已经 source 的终端：

```bash
ros2 run linkerbot_ffg_ros calibrate
```

`scripts/calibrate.sh`，脚本自己 source 后再执行 `ros2 run`：

```bash
scripts/calibrate.sh
```

配置见 [docs/config.md](docs/config.md)。

## 话题约定

**LinkerH**

| 方向 | 话题 |
|------|------|
| 出手指令 | `/cb_left_hand_control_cmd`、`/cb_right_hand_control_cmd`（`sensor_msgs/JointState`） |
| 力反馈入 | `/cb_left_hand_matrix_touch_mass`、`/cb_right_hand_matrix_touch_mass` |
| 型号识别 | `/cb_left_hand_info` 与 `/cb_right_hand_info` 的 `hand_joint`。已连接手套有上报时用该侧，两侧必须一致。手套没有 `hand_info`、只有对侧在发时，借用对侧型号并警告，指令仍发到手套自己的话题。完全读不到型号时要写明 `robot` |

**LinkerZ**

| 方向 | 话题 |
|------|------|
| 出手指令 | 该侧手部节点的 `.../command/angles`。没有该侧节点时不发布，不会改发到另一只手 |
| 型号识别 | `/linkerbot_hand/capabilities`（或 yaml 里改的 `capabilities_topic`） |
| 力反馈入 | 由该侧指令话题推出 `…/state/force_fns`、`…/state/force_fn`、`…/state/normal_force_resultant`。选定规则与 `force_topics` 相同：有效帧选定一次后只保留该路，之后不更换。驱动须 `force_hz>0` |
