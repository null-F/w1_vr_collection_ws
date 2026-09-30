# W1 PC1 L6 手套接入

独立目录 `/home/dexforce/linkerhand`，原始手套代码版本900a342，ROS2 Humble / Python3.10。
不修改 `/home/dexforce/w1`。可与 VR 同时运行：手套只驱动 L6，不控制机械臂，不启用手套触觉反馈。

## 使用

终端1运行 `bash /home/dexforce/linkerhand/repos/w1_glove_integration/start_hands.sh`。
此命令停止原厂 `dexe-devices.service` 以释放串口，使用同一原厂ee_server二进制，读取本目录内的双L6配置，输入话题隔离为 `/linkerhand/w1/ee/{left,right}/command`。
保持该终端打开。双手使用厂家速度100/100，对应原LinkerHand SDK的255/255速度档位。

终端2运行 `bash /home/dexforce/linkerhand/repos/w1_glove_integration/start_gloves.sh`。
按照原手套程序的终端提示完成三段标定；标定成功后开始跟随。每次默认重新标定，只有本人有效缓存可用时才加 `--reuse-calibration`。
仅观察映射可加 `--preview`，此模式只发布 `/linkerhand/preview/ee/*/command`，不进入手驱动。

Ctrl+C结束手套/桥接。停止发送新目标不等于电机失能。桥接不额外添加反馈等待、超时锁存或速度限制。
结束独立手驱动后，可用 `sudo systemctl start dexe-devices.service` 恢复厂家手服务。

## 接口与运行

手套输入仅选择VID:PID=1a86:7523的两个CH340串口，不扫描原有RS485/IMU串口。驱动未安装时入口会直接报告缺失。
启动入口会按需临时屏蔽brltty-udev.service（仅/run、本次开机有效），并从runtime/drivers加载已编译的CH341模块；没有执行make install、修改/lib/modules、替换内核或永久禁用服务。重启后由同一入口重新加载。需撤销临时屏蔽时执行 `sudo systemctl unmask --runtime brltty-udev.service`。
原手套L6六个电机量0..255经 `100*(255-x)/255` 转为厂家0..100；对应厂家库setPosMapping的逆变换，六个寄存器顺序不变。
原手套程序按自身配置发布（当前30Hz），保留原标定、L6映射、原有滤波及原有输出处理。
桥接每收到一帧就直接换算并转发，保留原消息时间戳；不增加定时重采样、新帧去重、平滑、变化率限制或反馈锁存。仅校验六维输入数值格式，不改变有效目标。
话题仍隔离为 `/linkerhand/w1/ee/{left,right}/command`，不发送手臂、底盘或使能命令。

## 文件

- `repos/linkerhand_ros_teleop/`：独立手套副本，保留原L6算法与终端标定。
- `config/w1/glove/`：本次部署配置，源码config目录指向这里。
- `runtime/calibration/glove/`：用户标定；不沿用仓库样本标定。
- `runtime/logs/`：日志。
- `runtime/venvs/glove-humble/`：独立Python环境，读取系统ROS依赖，不覆盖厂家Python包。

首次实机跟随仍需由操作者完成。代码/导入/预览检查不代表手运动验收。

## 串口重复启动排查结果（2026-09-29）

原外接扩展坞路径下，两种 CH341 驱动均出现首次可用、再次打开 USB 控制超时。将右手套直插机器人 USB（移除该外接扩展坞）后，标准驱动连续 5 次打开、识别、读取、关闭全部通过，每轮 41–42 帧、21 通道。
当前入口采用 runtime/drivers/linux-5.15.148-ch341/ch341.ko，源文件来自 Linux v5.15.148，以当前 NVIDIA RT 内核匹配头文件编译；未替换内核、未执行系统安装。请使用独立 USB 口或另行验证的扩展坞。双手同时直插的复测尚待完成。

2026-09-29 双手独立 USB 验证：路径 1-3.2 与 1-2.1.3，标准 CH341 驱动；双手同时读取、关闭、重新打开连续 5 轮通过。每手每轮 54–57 帧、21 通道，无 EIO。保留此连接方式，实手标定和运动验收仍由用户完成。
