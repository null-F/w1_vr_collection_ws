# PC1 离线提示音（手套标定 / MCAP）

## 现场拓扑与边界

依据用户提供的现场调试记录，**不是本次远程实测**：

```text
原提示链路：PC1 控制程序 → PC2:8766 语音服务 / 火山合成
                                    ↓ PulseAudio tunnel
                         PC1 的 Yundea M1051 USB 音箱

本次链路：PC1 控制程序 → 已打包的 WAV → PC1 本地 PulseAudio → 同一 USB 音箱
```

PC2 的 `yundea_speaker` 是隧道别名，不能直接作为 PC1 的真实声卡名。
本次明确指定 PC1 sink：

```text
alsa_output.usb-Yundea_Technology_Yundea_M1051_433039373936312E-01.analog-stereo
```

不使用系统默认 sink，不主动改默认声卡、音量、静音状态或模块；指定 sink 不存在时失败，不自动尝试板载声卡。
每次播放前查询该 sink，然后用 `paplay --server=... --device=...` 指定播放位置。
这是客户端启动时的路由保护；播放过程中 USB 拔出或音频服务器改变路由，仍需现场验证，不能仅靠配置证明一定可听。

**保持以下现场设置原样：**

- `VA_VAD_RMS_THRESHOLD=40000`，不改成 4000，不开启唤醒、对话或录音。
- 不改 PC2 `dexe-voice-agent.service`、`yundea-speaker.timer`，不加载/卸载隧道模块。
- 不改 PC2 两份 robot status `services.yaml` 中已清空的 `voice_notifications.charging_text`。
- 不改低电量、充满电和开机一次“机器人已启动”等厂家系统播报。
- 不关闭旧 PC2 服务，不删除其配置。它的其他系统播报是否仍需外网，不在本次离线化范围内。
- 不改厂家树 `/home/dexforce/w1`，不新增或修改任何 systemd unit/drop-in。

仅手套标定、手套状态和本项目 MCAP 状态提示离线化，不是整台机器人所有语音功能离线化。

## 文件与运行机制

- `local_voice.py`：仅 Python 标准库；PC1 上需要 `pulseaudio-utils` 提供 `paplay` / `pactl`。
- `../../config/w1/voice.json`：PC1 本地 Pulse socket、指定 USB sink、超时。
- `../../config/w1/voice_prompts.json`：22 条固定中文提示的 ID 和原文。
- `audio/zh_CN/`：WAV 和清单，校验 SHA256、原文、文件名、PCM16 格式、完整性和时长。
- `generate_voice_assets.py`：开发/制包工具，离线生成 WAV，机器人运行时不用它，也不需要合成模型。
- `runtime/voice/playback.lock`：本项目跨进程播放互斥；锁文件不要在进程运行中删除，否则可能产生两个互不相同的锁。

新旧手套入口共用本地播放模块。MCAP 沿用 `glove_manager.Voice` 导入接口，底层已改成本地音频队列。
`paplay` 的播放子进程完成后才返回；标定仍先播完该步提示，再调用 SDK 稳定采样。新 SDK 的串口轮询不中断。
X 取消时取消当前阶段的音频，释放锁并回收播放进程；状态队列的 `clear()` 同时清除排队和正在播放的旧提示。

各状态队列最多 32 条，超过 12 秒仍未获得播放机会的提示丢弃并记日志，避免很晚才播出过期状态。
播放锁只协调本项目的进程，**不阻止 PC2 原系统提示或其他应用混音**。
开始/保存/停止采集不等待声音；原 MCAP 操作顺序不变。状态音频失败只记日志；标定阶段音频失败则终止标定，不默默跳过提示进入跟随。

所有语音调用均无 PC2 HTTP、无运行时在线合成、无自动云端回退。
`--check` 只检查文件和命令是否可找到，不能证明声音可听。
`--check-output` 只向 PC1 本地音频服务查询 sinks，不播放、不开麦、不改音量。
管理服务原来的 `127.0.0.1:18770` X 键控制接口仍保留，它不是语音服务。

## PC1 上线前检查

本次没有在 PC1 执行以下命令，也没有部署或重启服务。先停止采集/手套跟随，再在维护窗口验收。
不要复制开发机 `/tmp` 里的工具到机器人，也不要复制 Jazzy 虚拟环境。

1. 以实际运行服务的用户检查工具和本地音频服务：

```bash
id
command -v paplay pactl
systemctl show dexe-tele.service linkerhand-w1-glove-manager.service -p User -p Group
pactl --server="unix:/run/user/$(id -u)/pulse/native" list short sinks
```

配置中的 `{uid}` 在每个进程中展开为该进程用户 ID，不硬编码开发机 UID=1000。
服务用户必须能连接 **PC1 已有的** PulseAudio socket；不要用 PC2 的 socket 或 `yundea_speaker` 隧道别名。
若 VR 服务与手套管理服务用户不同，分别检查连接权限。若现场 socket 路径不同，可在本项目配置中指定经过确认的本地 `unix:/...` 路径。
不要为绕过权限问题把服务改成 root、复制音频 cookie 或开放额外 TCP 权限。

若缺少客户端工具，由部署者在 PC1 安装发行版对应的 `pulseaudio-utils`；它不是 Python pip 包。
PC1 的音频服务还必须在**重启后、未交互登录时**可用；仅终端试播成功不能证明开机服务有权限或已经就绪。
本次没有自动修改用户服务 linger、音频守护进程或开机依赖，需先核对现场已有配置。

2. 在 PC1 部署目录进行无声检查：

```bash
cd /home/dexforce/linkerhand
python3 repos/w1_vr_glove_integration/local_voice.py --check
python3 repos/w1_vr_glove_integration/local_voice.py --check-output
```

若服务器不可达或 USB sink 不在列表中，先修复 PC1 音频出口。**不要改成 `default` 或板载声卡来绕过检查。**
可以用 `W1_VOICE_CONFIG` 指定另一份配置；`W1_VOICE_PULSE_SERVER` 只接受本地 unix socket；
`W1_VOICE_SINK` 只接受明确的 sink 名。命令明确传入 server/sink，不依赖继承的 `PULSE_SERVER` / `PULSE_SINK`。
为了让两个服务使用一致设置，优先修改本项目 `config/w1/voice.json`，而不是只在一个终端 export。

3. 经现场确认后才试播（此命令会发声）：

```bash
python3 repos/w1_vr_glove_integration/local_voice.py --play glove_open_full
```

逐条试听 `--list` 列出的提示，确认词义、音量和可懂度。现成音频是 **eSpeak NG 1.51 / cmn-latn-pinyin / UTF-8 / speed 170 的基础合成音色**，
不是原火山音色，未经目标音箱听感验收；单条约 2.2–7.4 秒。默认不提高现有音量，更不会自动执行现场记录中的 200% 放大命令。
去掉的是联网/云合成等待，不是句子本身的播放时间和 SDK 稳定采样时间，不能承诺具体提速倍数。

4. 在不驱动实手的受控验证阶段，检查新/旧标定五步/三步提示、X 取消、失败退出和新会话无旧声音残留；
随后按 SDK 迁移验收步骤验证实际跟随。采集单独检查开始、保存、取消、失败提示与真实结果一致，声音异常不阻塞停止/保存。
断开外网测试这两类提示；无须停用 PC2 系统服务。另在维护窗口确认 PC1 重启后的音频服务、权限、USB sink 名与出声位置。
USB 热拔插、其他应用混音和 PC2 系统提示并发仍需现场验证。

## 音频制包

当前库由开发机已有的 eSpeak NG 语言数据和 `/tmp` 解压的工具离线生成；未系统安装软件，未在开发机播放。
机器人只读取 WAV，不依赖 eSpeak NG、网络或推理模型。

需要换音色时，在制包机准备候选文件，不要在运行中的音频库上原位修改：

```bash
python3 repos/w1_vr_glove_integration/generate_voice_assets.py \
  --engine espeak-ng --output /tmp/w1-new-voice-bank
```

输出目录必须为空。生成器不访问网络、不播放、不覆盖既有文件。
默认使用 `cmn-latn-pinyin`，显式指定 `-b 1` 和 subprocess UTF-8。**不要再用旧 `cmn` 配置重建**：这版数据中它会把汉字替换后的拼音按英文读。
生成器检查同次合成产生的音素跟踪，拒绝外语回退；清单版本为 2。更新时必须整套同步 WAV 和 `manifest.json`。
具体缺陷复现和验证边界见 `audio/README.md`。
也可另行录制/合成相同文案，但必须保持 ID/原文对应、PCM16 WAV，并同步更新 `manifest.json` 的校验和和时长，再通过检查和试听后整体部署。
不允许用静音占位文件冒充有效提示，不在运行时自动补下载或合成缺失文件。

## 测试与验收边界

```bash
source /opt/ros/jazzy/setup.bash
export PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTHONPATH="$PWD/repos/linkerbot_ffg_ros2/src/linkerbot_ffg_ros:${PYTHONPATH:-}"
python3 -m pytest -q -p no:cacheprovider \
  repos/linkerbot_ffg_ros2/src/linkerbot_ffg_ros/test \
  repos/w1_glove_integration/tests \
  repos/w1_vr_glove_integration/tests
```

语音单测使用临时假 `paplay` / `pactl` 子进程，覆盖：原文/校验和/格式检查、PC1 精确路由、拒绝 TCP 和默认 sink、
设备缺失不回退、错误/超时/取消回收子进程、跨进程互斥、队列过期/清理、新旧标定先播后采、采集不等播报。
英文发音修复前：122 项功能测试通过，但未检测实际发音路径，漏掉了英文回退问题。修复后本轮结果：**134 passed**（原有 84 项 + 语音运行 38 项 + 音频生成回归 12 项），Python 3.10 语法边界检查和 shell 语法检查通过。
解包的 `paplay` / `pactl` 仅执行了 `--help`，核对参数；语音 `--check` 检查了全部 20 个真实 WAV，未连接开发机或机器人音频服务。
PC1 PulseAudio 可用性、真实服务权限、实际听感、开机和 Humble 环境均尚未实测。

## 回退

本次没有改 PC2 语音服务和音频隧道。若需要恢复旧播报，维护窗口先停止本项目采集/跟随，
部署第三项改动之前的代码版本（第一项 SDK 提交 `dfc1b31`），确认 PC2 服务及既有隧道正常后再启用业务。
不要使用本项目整体 `rollback.py` 只为撤回语音：它会同时撤回 VR/手套集成。

## 原理参考

播放参数按 PulseAudio `pacat/paplay`、`pactl` 随包手册核对：`--server` 选择服务器，`--device` 指定输出；
`pactl list short sinks` 查询出口。本次开发机解包版本为 pulseaudio-utils 16.1，目标机仍需用发行版自带工具验证。
https://www.freedesktop.org/wiki/Software/PulseAudio/Documentation/User/Network/
https://www.freedesktop.org/wiki/Software/PulseAudio/Documentation/User/Modules/
