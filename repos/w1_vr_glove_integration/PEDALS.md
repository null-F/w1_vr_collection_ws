# PC1 三联踏板单人遥操

踏板接 PC1 USB。当前配置按左、中、右上报键盘 A、C、E，分别对应方案中的手套、持续跟随和录制。PC1 上的各进程在启动时读取同一份 `config/w1/pedals.json`。仓库默认 `mode=dual`，现场核对设备并切到 `single` 后启用。

| 踏板 | 单人模式下的效果 |
| --- | --- |
| 左 A（键码 30） | 点踩启动五步手套标定。标定过程中再踩取消。听到“标定完成”后再踩会停止手套程序；下次启动重新标定。 |
| 中 C（键码 46） | 手套就绪且位姿有效时点踩一次申请跟随。听到“跟随已开启”后，即使抬脚，双臂和双手仍可跟随。再次点踩退出，录制继续。 |
| 右 E（键码 18） | 点踩开始一段 MCAP，再踩停止并保存。开录和保存结果由采集器返回。正在启动或保存时忽略新的右踏板请求；此时仍可点踩中踏板退出跟随。 |

左、右踏板可以在 VR 网页关闭时使用。转场或调整头显前，点踩中踏板退出并确认“跟随已关闭”，再按需停手套、移动底盘和重新标定。到新工位后点踩中踏板重新开启跟随，同一段录制延续到右踏板收尾。手套程序停止会停止发送手指目标，手驱动仍可保持当前位置。实际停止时延、再次使能的过渡和底盘转场流程需在现场确认。

## 识别设备

在 PC1 的 SSH 终端运行，按照 USB 插拔前后的设备链接确定踏板。先保持踏板服务停止，使用只读模式查看三键。脚本读取指定的一个设备，并打印内核键码和电平。

```bash
cd /home/dexforce/linkerhand
ls -l /dev/input/by-id /dev/input/by-path
read -r -p '请输入踏板的完整设备链接：' pedal_device
python3 repos/w1_vr_glove_integration/pedals.py --learn "$pedal_device"
```

1. 从左到右分别点踩，核对键码顺序和每一次的按下（1）、释放（0）。长按重复（2）会被服务忽略。
2. 中踏板支持瞬时脉冲。核对每次点踩只产生一对按下和释放，然后分别点踩中键、右键、中键，确认输入独立。
3. 在 `config/w1/pedals.json` 中填写上述稳定的 `device` 路径。若识别到的键码与预设不同，更新 `glove_key`、`hold_key`、`record_key`。服务启动时已经踩住的键要先松开才能使用。服务占用该输入接口期间字母不会传给桌面。

## 启用与退回

以下步骤适用于已部署本仓库手套管理、MCAP 常驻服务、独立 L6 命令话题和 VR 两个 drop-in 的 PC1。首次安装应先按工程 README 核对串口、手驱动和采集运行环境。配置切换安排在机器人静止、手套停止、采集已保存时，踏板保持松开。

```bash
cd /home/dexforce/linkerhand
systemctl cat dexe-tele.service linkerhand-w1-glove-manager.service linkerhand-w1-mcap.service
python3 repos/w1_vr_glove_integration/check_vendor.py
```

将 `mode` 改为 `single`，确认 `dexe-tele.service` 已加载 `50-linkerhand-vr-glove.conf` 和 `60-linkerhand-vr-mcap.conf`。踏板由独立服务读取，已有服务也要重启以加载同一模式。

```bash
sudo systemctl link /home/dexforce/linkerhand/repos/w1_vr_glove_integration/linkerhand-w1-pedals.service
sudo systemctl daemon-reload
sudo systemctl restart linkerhand-w1-glove-manager.service linkerhand-w1-mcap.service
sudo systemctl enable --now linkerhand-w1-pedals.service
sudo systemctl restart dexe-tele.service
journalctl -u linkerhand-w1-pedals.service -n 30 --no-pager
curl -s http://127.0.0.1:18770/status
```

回到双人操作时，先结束录制、松踏板、停手套，执行 `sudo systemctl disable --now linkerhand-w1-pedals.service`，把 `mode` 改回 `dual`，再重启手套管理、MCAP 和 VR 三个服务。重新打开 VR 页面。双人模式仍通过 X 管手套、双握配合左摇杆管理录制。两种模式共用 30 路话题配置。

## 验收与数据

- 首先用 `pedals.py --learn` 确认三键各自的点踩事件。之后在预览或不连接执行器的环境验证手套就绪、等待新踩踏、第二次点踩停发、VR 位姿丢失、拔插踏板和重新使能。最后验证实机停用点踩至末条命令和实际停止的时间，观察重新使能是否出现跳变。
- `/run/linkerhand-w1-pedals/pedal.json` 记录输入心跳，`vr.json` 记录厂家遥操使能回执。`hands.json` 来自本次手套会话的双手输入。心跳有效期为 250 ms，看护循环间隔为 40 ms。两者是软件参数，调度、网络、驱动和机构响应会影响实测时延。
- 单人模式的 `episode.json` 在右踏板开录时标记 `source=pedal`。`operator_events.jsonl` 保存开始状态、手套阶段、踏板连接与中键电平、厂家跟随使能变化及结束时间。事件使用 PC1 观察到的墙钟纳秒。手套阶段、跟随使能与是否正在录制是三个独立状态。
- 全量验收覆盖一段包含转场和二次标定的录制。点踩中踏板退出跟随、关闭 VR 和左踏板停止手套之后，右踏板应仍能保存同一段。终端已开录时右踏板应收到归属冲突。回放和缺流检查见采集工程说明。

## 手背手柄安装补偿

单人模式在读取原始手柄位姿后、厂家坐标变换和 IK 之前，应用 config/w1/controller_offsets.json。左右分别配置 translation_m（米）和 rotation_xyz_deg（度，固定轴 XYZ 欧拉角，与 SciPy 小写 xyz 一致）。计算使用 T_corrected = T_controller × T_offset，平移在当前手柄局部坐标系中表达，随手柄朝向旋转。

当前右手补偿来自 2026-11-24 掌心/手背两组 WebXR 采样，采用 inv(T_back) × T_palm：translation_m=[-0.1133458832, 0.0684921509, -0.0186485947]，rotation_xyz_deg=[35.3649461, -5.6552765, -21.6712305]。左手暂按左右对称安装镜像，以 M=diag(-1,1,1) 计算 t_left=M×t_right、R_left=M×R_right×M；在固定轴 xyz 欧拉角下对应 [rx,-ry,-rz]。左手尚未独立标定，需实机确认对称安装和手腕静止假设。机器人厂家配置 teleop_config.yaml 的 teleop_spatial_mode 恢复为 absolute；此配置位于机器人厂家工程中，补偿在绝对/增量模式下均先于厂家映射应用。原始追踪位姿和补偿后的位姿都会经过有效性检查。既有厂家映射和 IK 接收补偿后的手柄目标。

配置在 VR 进程初始化时读取，修改后需在退出跟随、保存录制后重启 dexe-tele.service，再进入网页测试。enabled=false 可关闭补偿。双人模式沿用原握持入口。启动日志中的 LINKERHAND_CONTROLLER_OFFSETS 输出本次使用的配置。

## Ready 回位

单人模式长按左手 Y 约 2 秒，恢复 config/w1/ready_pose.json 的身体及双手位置；回位期间暂停实时跟随，结束后重新踩 C 开始下一轮。B 原功能保持不变，E 的 MCAP 录制不自动停止。操作条件与故障处理见 READY_POSE.md。

手背安装补偿的可视化调参入口见 [OFFSET_PREVIEW.md](OFFSET_PREVIEW.md)。页面只预览和保存待用参数，不热更新、不使能机器人。
