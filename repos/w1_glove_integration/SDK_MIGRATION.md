# W1 手套 SDK 切换说明（2026-11-03）

## 范围与版本

- 新 SDK：`repos/linkerbot_ffg_ros2`，上游 `linker-bot/linkerbot-ffg-ros2`。
- 固定分支/提交：`master@6da23b796c14b4bed8eaadecdf193f8058fe67ed`。
- 127 个上游文件按原样导入，保留 Apache-2.0 LICENSE；来源和逐文件 SHA256 见该目录 `UPSTREAM_VERSION.json`。
- 默认启动选择 `W1_GLOVE_SDK=ffg`；不自动跟随上游更新，也不在失败时静默切回旧版。
- 旧 SDK、旧配置和标定缓存保留，显式选择 `W1_GLOVE_SDK=legacy` 才会使用。
- 不修改厂家 `ee_server`、手驱动速度、W1 桥接数值公式、采集话题、MCAP 格式或 VR 录制状态机。
- **不包含清单第2项触觉缺维修复，也不包含第3项离线语音替换。**

本次是代码适配，未部署到机器人。不要把离线测试通过当作 Humble、串口或手运动验收通过。

## 新旧差异

| 项目 | 旧 SDK | 新 SDK / 本次适配 |
|---|---|---|
| 包名 | `linkerhand_retarget` | `linkerbot_ffg_ros` |
| 实际入口 | `handretarget` / 旧 `glove_entry.py` | W1 `ffg_entry.py` 组合 SDK 组件 |
| SDK 标定 | 握拳 / O 型 / 张开 | 完全张开 / 五指并拢 / 点赞 / 五指聚拢捏 / 拇指指尖弯向根部 |
| L6 映射 | 旧多状态映射及输出处理 | 新 `GloveChangeEstimator` + `L6Mapper` |
| 指令 | 六维 `JointState`，0..255 | 保持相同桥接接口；数值行为不保证等价 |
| 配置 | `config/w1/glove/*.yml` | `config/w1/glove_ffg.yaml` |
| 标定缓存 | `runtime/calibration/glove/jointangle_data.tmp` | `runtime/calibration/glove_ffg/glove_{side}_*.yaml` |
| 串口 | SDK 后台读线程 | SDK 主线程轮询；语音 HTTP 在独立线程，等待时主线程继续轮询 |
| 失联 | 旧 SDK 的处理 | 新 SDK 最后有效帧起最多1秒保留/重发上一指令，之后停止发布；不等于电机失能 |
| 环境 | 现场 Humble / Python3.10 | 上游声明 Jazzy / Python3.12；W1 适配仍接现场 Humble，需目标验证 |

新 SDK 上游默认启用 LinkerZ、自动扫串口和力反馈，**不能直接拿默认 launch/script 在 W1 上运行**。
本工程使用独立 W1 profile：`l6 + LinkerH + auto_scan=false + force_feedback=false`。

`ffg_entry.py` 只组合 SDK 的读取、标定、映射、输出组件，不使用依赖手驱动自动发现的通用应用主函数。
这样可继续使用厂家 ee_server，无需替换为 LinkerH/LinkerZ 手驱动，也无需构建 LinkerZ 自定义消息包。
唯一的标定观察 hook 包装 `capture_pose_multi` 调用，在稳定采样前发阶段事件并等待语音，退出时恢复原函数。

## 保留的控制边界

```text
FFG SDK 的 LinkerH JointState（六维，开=255，合=0）
  /cb_{left,right}_hand_control_cmd
    --ROS重映射-->
  /linkerhand/glove/{left,right}/motor_cmd
    --原 w1_hand_bridge: (255-x)*100/255-->
  /linkerhand/w1/ee/{left,right}/command
    --> 厂家 ee_server
```

- 仍只选择 VID:PID=1a86:7523 的两只可读写串口，实际左右由手套协议识别。
- 两只口不齐、侧别重复、版本查询失败时拒绝跟随；不扫描机器人其他串口。
- 固定30Hz，W1 平滑参数保留 alpha=0.5、max_step=20；不修改新 SDK 算法以模仿旧版。
- 新 SDK 的首次平滑初始化与旧版不同；特别是从静止开始跟随时，需要操作者检查跳变。
- `--preview` 仍只改变桥接输出到 `/linkerhand/preview/ee/*/command`。
- `hands.lock` / `gloves.lock` 及两条入口保持共用；不要直接调用 `ffg_entry.py` 启动实机，常规启动走 shell 入口。
- 新旧标定目录完全分开；首次必须重新标定，不能把旧 `.tmp` 或仓库样例复制为新有效缓存。
- `--reuse-calibration` 只读取新目录双手最新文件，验证五态、侧别和有限数值；不会验证“当前操作者身份”，由操作者保证缓存属于本人。
- VR X 启停、手驱动与采集逻辑保持原约定；新阶段事件被原 manager 接收。

## 目标机部署前检查

在维护窗口停止当前手套跟随后再同步代码。不要在正在标定/跟随时更新源码。

在 PC1 的部署目录执行以下**导入检查**（不启动节点、不打开设备、不调用语音）：

```bash
cd /home/dexforce/linkerhand
source repos/w1_glove_integration/env.sh
python repos/w1_glove_integration/ffg_entry.py --check
```

这会显示所用提交、Python、W1 profile 和新缓存位置。检查本身没有 ROS 节点/设备写入；`env.sh` 沿用原逻辑，会准备 ROS 日志目录。

默认复用现有 `runtime/venvs/glove-humble`，依赖仍由上游 `requirements.txt` 说明（numpy<2、PyYAML、pyserial），并读取系统 ROS Python 包。
若导入/NumPy 版本检查失败，先在独立虚拟环境补齐依赖，再通过 `W1_GLOVE_VENV` 指定该环境；不要升级厂家系统 Python，也不要为试新版覆盖旧 SDK 环境。

**当前机器没有 Python3.10 / ROS Humble，未证明目标环境兼容。** Python3.10 语法检查只能排除语法层面的不兼容，不能替代目标机导入、ROS ABI 和实机通信检查。
如果目标机检查失败，不启动实机跟随；保留旧入口，先定位具体依赖/API差异，不把整台 W1 切到 Jazzy。

## 逐级验收

1. 目标 Humble 环境运行 `--check`，确认不依赖 LinkerZ 消息生成。
2. 确认没有其他手套进程/桥接占用；用终端预览入口验证五态标定、串口识别、双手六维指令：
   ```bash
   bash repos/w1_glove_integration/start_gloves.sh --preview
   ```
   该入口仍会准备 CH341 驱动，可能请求 sudo；不是纯离线检查。
3. 分别验证两手的张开、弯曲以及拇指两轴顺序，检查有效输出范围、首次跟随跳变、30Hz和失联策略。
4. 在现场操作者控制下进行实手跟随验收。保持现有安全措施；停止发布不是电机失能。
5. 验证 VR X 启动五步标定、语音在采样之前、再次 X 取消/停止、失败不播报成功。
6. 验证 `--reuse-calibration` 只复用当前本人新缓存；旧 `.tmp` 不读取、不删除。
7. 最后验证 MCAP 中左右手最终 action/state 的话题、六维顺序和0..100单位未变化。

新五态标定保留上游每态预备/稳定时间，不因这次切换缩短采样，也没有对在线语音做离线替换。

## 显式回退

先停止新版手套进程，再从终端选择旧版：

```bash
W1_GLOVE_SDK=legacy bash repos/w1_glove_integration/start_gloves.sh --preview
# 完成预览和现场确认后，去掉 --preview 才进入实手输出。
```

VR 服务入口同样读取环境变量：在 `linkerhand-w1-glove-manager.service` 的**本地 drop-in**中设置：

```ini
[Service]
Environment=W1_GLOVE_SDK=legacy
```

由操作者在停止手套后重载/重启管理服务，下一次 X 才会启动旧入口。旧版仍使用旧三态标定与缓存。
恢复新版时移除该设置或改为 `ffg`。若使用独立虚拟环境，也应同时确认 `W1_GLOVE_VENV` 选择正确。
此 SDK 回退不需要运行整个 VR/MCAP 的 `rollback*.py`，不会删除任何采集或标定数据。

## 开发验证

本次在 Jazzy/Python3.12 环境执行，测试不访问串口、语音服务或机器人，不创建真实 ROS 节点：

```bash
source /opt/ros/jazzy/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTHONPATH="$PWD/repos/linkerbot_ffg_ros2/src/linkerbot_ffg_ros:${PYTHONPATH:-}"
python3 -m pytest -q -p no:cacheprovider \
  repos/linkerbot_ffg_ros2/src/linkerbot_ffg_ros/test \
  repos/w1_glove_integration/tests
```

覆盖上游协议、映射、标定和失联逻辑，以及 W1 profile、USB候选/左右识别、映射到桥接单位、缓存拒绝、五态事件、语音失败、默认重新标定、显式复用与资源清理。
上游源文件完整性和 Python3.10 语法边界也纳入检查。真实性边界见上面的目标机验收说明。

### 本轮执行结果

- 上述 pytest 命令：**84 passed**（上游39项 + W1适配/启动脚本45项）。
- 新 SDK 的127个源文件哈希全部与导入清单一致；上游文件未作本地算法修改。
- 新入口 `--check` 在本机 Jazzy / Python3.12.3 通过。
- 相关 shell 脚本 `bash -n` 通过，`git diff --check` 通过。
- 另做了一次真实 Jazzy 话题解析检查：仅限 localhost、ROS域79，创建检查节点后确认两个 publisher 的最终话题是 `/linkerhand/glove/{left,right}/motor_cmd`；**没有发布任何运动消息，也没有访问设备**。此检查只验证 ROS 重映射，不证明 Humble ABI 或实手控制正确。
- 未执行：Humble/Python3.10运行、CH340实设备通信、五态实人标定、PC2语音联调、双L6运动、MCAP实机回归。
