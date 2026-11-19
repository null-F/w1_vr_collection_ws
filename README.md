# W1 VR 手套遥操与 MCAP 采集

单人操作使用 PC1 USB 三联踏板。按键识别、模式切换和上机验收见[三联踏板接入说明](repos/w1_vr_glove_integration/PEDALS.md)。

这是 DexForce W1 上的独立目录，部署在 PC1 的 `/home/dexforce/linkerhand`。手套控制双手 L6，Quest 3 遥操控头、腰、双臂和底盘，采集单独写成 MCAP。不修改厂家树 `/home/dexforce/w1` 里的源文件。

## 目录

| 路径 | 作用 |
|---|---|
| `repos/linkerbot_ffg_ros2` | 新 FFG 手套 SDK，默认入口使用；固定上游版本 `6da23b7` |
| `repos/linkerhand_ros_teleop` | 旧 LinkerForce SDK，仅供显式回退，未删除 |
| `repos/w1_glove_integration` | 手套到 W1 双手的适配、串口准备和手驱动启动 |
| `repos/w1_mcap_collection` | 只订阅、不发运动命令的 MCAP 采集 |
| `repos/w1_vr_glove_integration` | 左手柄 X 键标定，握柄加左摇杆录制 |
| `config/w1/glove_ffg.yaml` | 新 SDK 的 W1 配置：L6 / LinkerH / 30 Hz / 关闭力反馈 |
| `config/w1/glove` | 旧 SDK 配置，回退时使用 |
| `config/w1/voice.json` | PC1 离线提示音配置，固定本地 PulseAudio socket 和 Yundea USB sink |
| `runtime/` | CH341 驱动、MCAP 插件、标定和运行锁 |
| `arms_hang.json` | 从现场关节状态抄下的准备姿态 |

`runtime/venvs`、运行日志、锁文件和已解压的内核头文件没有放进仓库。Python 环境在机器人上位于 `runtime/venvs/mcap-collection`。MCAP 插件解压在 `runtime/mcap_prefix`。

旧手套包保留三处符号链接，供回退使用；新 SDK 不使用这些配置和缓存：

- `linkerhand_retarget/config` → `config/w1/glove`
- `motion/linkerforce/tmp` → `runtime/calibration/glove`
- `motion/linkerforce/log` → `runtime/logs/glove`

## 手套 SDK 切换

默认入口已改接 `linkerbot-ffg-ros2`，旧 SDK 保留为 `W1_GLOVE_SDK=legacy` 显式回退。
新标定写入 `runtime/calibration/glove_ffg/`，不读取旧 `jointangle_data.tmp`，首次必须重新做五步标定。
SDK 切换没有更换厂家手驱动或修复触觉维度。后续手套/采集离线提示音改造见下文，厂家系统播报保持不变。

**当前是仓库侧适配，不是实机验收结论。** 上游声明 Jazzy/Python 3.12，W1 仍使用 Humble/Python 3.10；
Humble 运行、USB 通信和六轴方向需在目标机验证。操作与回退见 `repos/w1_glove_integration/SDK_MIGRATION.md`。

## 手套和手

`start_hands.sh` 使用原厂 `ee_server`，把命令话题改到：

- `/linkerhand/w1/ee/left/command`
- `/linkerhand/w1/ee/right/command`

Quest 扳机发到 `/control/ee/*` 的命令不会驱动这双手。`w1_hand_bridge.py` 把手套的 0 到 255 转成厂家末端的 0 到 100，约 30 Hz。手套力反馈当前是关的。

串口驱动由 `prepare_glove_usb.sh` 加载，只认 VID:PID `1a86:7523` 的 CH340。

## VR 操作

开机后手驱动和 VR 遥操由服务拉起。手套不会自动跟随。

左手柄 X 短按一次并松开：新 SDK 按语音依次做完全张开、五指并拢、点赞、五指聚拢捏、拇指指尖弯向拇指根，完成后开始跟随。再短按一次：标定中取消，跟随中停止。停止手套不会关闭手驱动。

两侧握柄都按住时，单击左摇杆开始录制，再单击或松开任一握柄则停止并保存。这两类提示改为 PC1 本地 WAV，定向播放到 Yundea USB 音箱，不再经 PC2 合成。终端采集命令仍然可用：

```bash
bash repos/w1_mcap_collection/record.sh start <任务名>
bash repos/w1_mcap_collection/record.sh stop
bash repos/w1_mcap_collection/record.sh cancel
bash repos/w1_mcap_collection/record.sh status
```

VR 入口的任务名在 `repos/w1_vr_glove_integration/mcap_settings.json`，当前是 `vr_glove`。数据写到：

```text
/home/dexforce/collection_data/<任务名>/raw/episode_XXXXXX/
```

每段包含 `raw/raw_0.mcap`、`raw/metadata.yaml`、`device_info.json`、`recording_info.json` 和 `episode.json`。缺话题仍允许封包，缺的话题记在 `missing_topics`。采集保留各话题自己的时间戳，不做跨传感器对齐。

相关服务：

- `linkerhand-w1-glove-usb.service`
- `linkerhand-w1-glove-manager.service`
- `linkerhand-w1-mcap.service`

回滚先运行 `rollback_mcap.py`，再运行 `rollback.py`。回滚不删除已经录好的数据和标定缓存。

## PC1 离线提示音

固定提示音库和入口已接入；不是音频设备、Humble 或开机实机验收结论。
音频出口按现场记录固定为 PC1 的 Yundea M1051 USB sink，而非 PC2 的 `yundea_speaker` 隧道别名或默认声卡。
`paplay` / `pactl` 连接本地用户 PulseAudio socket；不新增常驻服务、不改麦克风/默认声卡/音量/隧道或原语音服务。
保留 `VA_VAD_RMS_THRESHOLD=40000`、关闭唤醒对话、已清空的充电插入提示，以及厂家低电量/充满电/开机提示。
语音文件使用基础合成音色，仍需 PC1 试听和服务用户权限、未登录时开机音频服务就绪验证。
配置、无声检查、试听和回退见 `repos/w1_vr_glove_integration/OFFLINE_VOICE.md`。

## 准备姿态

```bash
source ~/.dex_env.sh
cd ~/w1/dexe_mobile_application/script
python3 slowly_move_to.py /home/dexforce/linkerhand/arms_hang.json
```

`arms_hang.json` 里的 20 个身体关节来自当时的 `/feedback/joint`。写文件时手部状态没有发布者，手指是张开的 0。
