# W1 PC1 L6 手套接入

独立目录 `/home/dexforce/linkerhand`，W1 部署环境为 ROS2 Humble / Python3.10。
默认使用新 FFG SDK `6da23b7`；旧 SDK `900a342` 保留用于显式回退。
新上游声明 Jazzy/Python3.12，本工程的 Humble 接入需要目标机验证；详见 `SDK_MIGRATION.md`。
不修改 `/home/dexforce/w1`。可与 VR 同时运行：手套只驱动 L6，不控制机械臂，不启用手套触觉反馈。

## 使用

终端1运行 `bash /home/dexforce/linkerhand/repos/w1_glove_integration/start_hands.sh`。
此命令停止原厂 `dexe-devices.service` 以释放串口，使用同一原厂ee_server二进制，读取本目录内的双L6配置，输入话题隔离为 `/linkerhand/w1/ee/{left,right}/command`。
保持该终端打开。双手使用厂家速度100/100，对应原LinkerHand SDK的255/255速度档位。

终端2运行 `bash /home/dexforce/linkerhand/repos/w1_glove_integration/start_gloves.sh`。
按照新手套程序的终端提示完成五步标定（完全张开、五指并拢、点赞、五指聚拢捏、拇指指尖弯向根部）；标定成功后开始跟随。每次默认重新标定，只有本人有效的新格式双手缓存可用时才加 `--reuse-calibration`。旧 `.tmp` 不能复用。
仅观察映射可加 `--preview`，此模式只发布 `/linkerhand/preview/ee/*/command`，不进入手驱动。

Ctrl+C结束手套/桥接。停止发送新目标不等于电机失能。桥接不额外添加反馈等待、超时锁存或速度限制。
结束独立手驱动后，可用 `sudo systemctl start dexe-devices.service` 恢复厂家手服务。

## 接口与运行

手套输入仅选择VID:PID=1a86:7523的两个CH340串口，不扫描原有RS485/IMU串口。驱动未安装时入口会直接报告缺失。
启动入口会按需临时屏蔽brltty-udev.service（仅/run、本次开机有效），并从runtime/drivers加载已编译的CH341模块；没有执行make install、修改/lib/modules、替换内核或永久禁用服务。重启后由同一入口重新加载。需撤销临时屏蔽时执行 `sudo systemctl unmask --runtime brltty-udev.service`。
原手套L6六个电机量0..255经 `100*(255-x)/255` 转为厂家0..100；对应厂家库setPosMapping的逆变换，六个寄存器顺序不变。
新 SDK 通过 LinkerH JointState 输出接现有桥接，W1 配置为30Hz、平滑alpha=0.5、max_step=20。使用新 SDK 的五态标定、归一化L6映射和失联处理，算法和首次平滑行为不保证与旧 SDK 数值等价；六轴实手方向和跟随效果须重新验收。
桥接每收到一帧就直接换算并转发，保留原消息时间戳；不增加定时重采样、新帧去重、平滑、变化率限制或反馈锁存。仅校验六维输入数值格式，不改变有效目标。
话题仍隔离为 `/linkerhand/w1/ee/{left,right}/command`，不发送手臂、底盘或使能命令。

## 文件

- `repos/linkerbot_ffg_ros2/`：固定版本的新 SDK，完整保留上游文件和许可证，不在其中修改算法。
- `ffg_entry.py`：W1 串口白名单、双手检查、ROS话题重映射、五步标定事件与进程收尾。
- `repos/linkerhand_ros_teleop/`：旧 SDK 回退副本。
- `config/w1/glove_ffg.yaml`：新 SDK 的 W1 部署配置。
- `config/w1/glove/`：旧 SDK 的回退配置。
- `runtime/calibration/glove_ffg/`：新 SDK 用户标定；不使用仓库样例。
- `runtime/calibration/glove/`：旧 SDK 缓存，保留且不自动转换。
- `runtime/logs/`：日志。
- `runtime/venvs/glove-humble/`：默认复用现有独立Python环境；可通过 `W1_GLOVE_VENV` 指定另一环境，不覆盖厂家Python包。

首次实机跟随仍需由操作者完成。代码/导入/预览检查不代表手运动验收。

## 串口重复启动排查结果（2026-09-29）

原外接扩展坞路径下，两种 CH341 驱动均出现首次可用、再次打开 USB 控制超时。将右手套直插机器人 USB（移除该外接扩展坞）后，标准驱动连续 5 次打开、识别、读取、关闭全部通过，每轮 41–42 帧、21 通道。
当前入口采用 runtime/drivers/linux-5.15.148-ch341/ch341.ko，源文件来自 Linux v5.15.148，以当前 NVIDIA RT 内核匹配头文件编译；未替换内核、未执行系统安装。请使用独立 USB 口或另行验证的扩展坞。双手同时直插的复测尚待完成。

2026-09-29 双手独立 USB 验证：路径 1-3.2 与 1-2.1.3，标准 CH341 驱动；双手同时读取、关闭、重新打开连续 5 轮通过。每手每轮 54–57 帧、21 通道，无 EIO。保留此连接方式，实手标定和运动验收仍由用户完成。
