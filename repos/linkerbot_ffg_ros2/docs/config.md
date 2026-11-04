# 配置文件说明

主配置：[src/linkerbot_ffg_ros/config/default.yaml](../src/linkerbot_ffg_ros/config/default.yaml)。安装后位于 `share/linkerbot_ffg_ros/config/default.yaml`。不传 `--config` 时读这一份，不会自动改用家目录里的文件。

本机要改配置时，复制后再传 `--config`：

```bash
mkdir -p ~/.config/linkerbot_ffg_ros
cp "$(ros2 pkg prefix linkerbot_ffg_ros)/share/linkerbot_ffg_ros/config/default.yaml" \
   ~/.config/linkerbot_ffg_ros/default.yaml
ros2 run linkerbot_ffg_ros teleop --config ~/.config/linkerbot_ffg_ros/default.yaml
```

**CLI 能覆盖的字段有限**，不是整份 yaml 都能用命令行改。当前 `teleop_node.py` 支持：

| CLI | 覆盖的配置 |
|-----|------------|
| `--config` | 换一份 yaml |
| `--robot` / `--hand-sdk` | `system.robot` / `system.hand_sdk` |
| `--rate` / `--calib-dir` | `teleop.rate_hz` / `teleop.calib_dir` |
| `--no-smooth` / `--smooth-alpha` / `--smooth-max-step` | 平滑相关（`--no-smooth` 关平滑；后两项覆盖系数） |
| `-F` / `--no-force-feedback` | 力反馈开关与可选 `max_force` |
| `--port` / `--baud` | 扫口时的端口/波特率（见下方串口说明） |
| `--skip-calibrate` / `--print` | 仅行为开关，无对应 yaml 字段 |

`linker_z.*`、力反馈曲线常量（`trigger_mass` 等）只能改 yaml。`smooth` 的开/关无独立 CLI 开项，只能 yaml 开或 `--no-smooth` 关。

## `system` — 型号与后端

| 参数 | 含义 |
|------|------|
| `robot` | 机械手型号。`auto`：按 `hand_sdk` 自动识别（Z 订 capabilities；H 只读 `/cb_*_hand_info`）。某一侧没有驱动时：H 仍向该侧话题发指令并警告；Z 该侧不发布，避免打到另一只手。已连接的两侧型号不一致，或完全读不到型号时，把 `robot` 写成具体型号。也可写死 `o6` / `l6` / `l10` / `l20lite` / `o30` / `l20`。对应 CLI：`--robot` |
| `hand_sdk` | 手部驱动后端。`LinkerH` → 发 `/cb_*_hand_control_cmd`；`LinkerZ` → 发 `/linkerbot_hand/command/angles`（RAW）。对应 CLI：`--hand-sdk` |

## `linker_z` — 仅 LinkerZ 时

| 参数 | 含义 |
|------|------|
| `client_id` | 发给 Z 指令消息用的 client 标识（与驱动约定一致，默认 `1`） |
| `command_topic` | 保留字段。某一侧没有手部节点时不会退回这条共用话题，避免左右手串控 |
| `topics.left` / `topics.right` | 左右手指令话题。`null` 表示使用该侧手部节点的 `.../command/angles`。该侧没有节点时不发布。两只手话题相同时启动失败 |
| `capabilities_topic` | 额外订阅的型号能力话题，默认 `/linkerbot_hand/capabilities`。图上其他 `.../linkerbot_hand/capabilities` 也会读取 |
| `discover_timeout_sec` | 自动识别等待超时（秒） |
| `force_topics.left` / `right` | 力反馈话题。`null`：先订 `force_fns`、`force_fn`、`normal_force_resultant`。有效帧是 `meta.valid` 为真且 `meta.stale` 为假。`force_fns` 一有有效帧就选定；若先出现的是后两路，再等 0.5 秒，期间更高优先级有有效帧则选更高的。选定后只保留这一路，本次运行不再更换；这一路后来没数据也不改订另一路。写了话题则只在这些话题里做同一次选定。驱动须 `force_hz>0` |
| `o30_swap_01` | 仅 O30 + LinkerZ：发出去前是否交换索引 0/1（拇指两轴）。实机两轴对调时改为 `true` |

`hand_sdk: LinkerH` 时整段忽略。

## `serial` — 手套串口

| 参数 | 含义 |
|------|------|
| `auto_scan` | `true`：扫描候选串口。`false`：只打开 `left.port` 和 `right.port` |
| `baudrates` | `auto_scan: true` 且未传 `--baud` 时尝试的波特率列表 |
| `left.port` / `right.port` | `auto_scan: false` 时使用的串口 |
| `left.baudrate` / `right.baudrate` | 这两个串口各自的波特率 |

| 方式 | 含义 |
|------|------|
| 不传 `--port`，且 `auto_scan: true` | 扫描 `/dev/ttyUSB*`、`/dev/ttyACM*`、`/dev/ttyXRUSB*`、`/dev/ttyOBC*` |
| `--port /dev/ttyUSBx` | 只试这一只口 |
| `--baud` | 只试该波特率 |

## `teleop` — 遥操循环

| 参数 | 含义 |
|------|------|
| `rate_hz` | 主循环频率（Hz）。对应 CLI：`--rate` |
| `smooth` | 是否对电机指令做平滑。对应 CLI：`--no-smooth` 可关 |
| `smooth_alpha` | EMA 系数：`out = α·raw + (1-α)·prev`，越大越跟手、越抖。对应 CLI：`--smooth-alpha` |
| `smooth_max_step` | 每周期电机值最大变化量（限速）。对应 CLI：`--smooth-max-step` |
| `calib_dir` | 标定文件目录。`null` 时先看 `LINKERFORCE_CALIB_DIR`，否则用 `~/.local/share/linkerbot_ffg_ros/calibration`。对应 CLI：`--calib-dir`。`--skip-calibrate` 时从此目录取该侧最新标定。成功保存后删除该侧更旧的文件，另一侧不动 |

## `force_feedback` — 力反馈（H / Z 共用规则）

决定优先级：

1. CLI：`--no-force-feedback` 强制关；`-F` / `-F MAX` 强制开（可选覆盖 `max_force`）
2. 未给 CLI 时：`by_robot.<型号>.enabled` → `force_feedback.enabled` → `default.enabled`
3. `max_force`：`by_robot.<型号>` → `default`；最终再钳到 `hardware_limit`

| 参数 | 含义 |
|------|------|
| `enabled` | 总开关；两套后端默认都开。`false` 则默认全体关（仍可被 `-F` 打开） |
| `trigger_mass` | 触觉质量低于此值时不出力（死区起点）。配置为负时启动失败 |
| `mass_max` | 映射用的质量上限，超过按此封顶 |
| `force_onset` | 刚越过死区时手套力的起始值 |
| `hardware_limit` | 力反馈指令的软件配置上限；所有 `max_force` 不能超过它 |
| `default.enabled` | 未写 `by_robot` 开关时的默认开/关 |
| `default.max_force` | 未写型号专用 `max_force` 时的默认上限 |
| `by_robot.<型号>.max_force` | 按型号覆盖力上限（如 L6 可用到 1000） |
| `by_robot.<型号>.enabled` | （可选）按型号单独开/关力反馈 |

触觉输入来源见 [话题约定](../README.md#话题约定)。LinkerH 当前只订矩阵触觉话题，没有矩阵则无力反馈（手仍能动）。
