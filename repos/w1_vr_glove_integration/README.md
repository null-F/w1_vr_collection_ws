# W1 VR X 键手套与开机启动

部署在 PC1 /home/dexforce/linkerhand/repos/w1_vr_glove_integration。
厂家 /home/dexforce/w1 下文件保持原样；服务附加配置加载此目录中的运行时补丁。

## 操作

开机后双 L6 驱动和 VR tele 服务自动启动。USB 准备与管理服务后台运行，手套不会自动跟随。
首次部署后重新打开或刷新 VR 网页，使 X 键补丁加载。
左手柄 X 短按一次并松开（不要双击）：启动手套并重新标定。
机器人扬声器依次播报：握拳、O型、五指张开、标定完成并启动遥操。
每阶段先完成语音提示，再调用原程序的稳定采样；串口读取线程持续运行。标定仍由原程序按真实稳定状态推进。X 再次短按：标定中取消，跟随中停止。
结束进程后播报取消或停止；停止手套不会关闭手驱动或使手电机失能。
X 双击、长按、其他组合键与原厂一致。X 短按不再切换左手手势。
手套不增加 VR 状态界面。录制按键现已接入 MCAP，操作见下文。

## 运行边界

- 原手套映射、滤波、标定判定、30Hz配置以及直通桥接均不改变。
- 手驱动使用厂家原 ee_server，双手 speed=100，输入隔离到 /linkerhand/w1/ee/{left,right}/command。
- glove_entry.py 只包装原标定阶段/返回结果并输出事件，不改算法。
- 语音通过 PC2 http://192.168.20.21:8766/voice_agent/speak 执行。阶段提示在开始该步采样前完成；成功/停止播报由独立管理线程执行，不阻塞遥操。
- 管理入口仅监听 127.0.0.1:18770。原厂已占用8770，不使用该端口。
- USB驱动准备由root系统服务执行；手驱动、手套及管理服务使用dexforce，不存储密码。
- 手套不自动重启或复用旧标定；启动失败/异常退出会播报失败，不冒充标定成功。
- 长按和双击仍由原识别器仲裁，普通短按可能等待约300ms双击识别窗口。

## 服务与检查

systemctl status dexe-devices.service dexe-tele.service linkerhand-w1-glove-manager.service
curl -s http://127.0.0.1:18770/status
journalctl -u linkerhand-w1-glove-manager.service -n 50 --no-pager

标定原始输出与状态：/home/dexforce/linkerhand/runtime/vr_glove/。
不与旧终端手套程序同时运行；启动脚本共用原有gloves.lock/hands.lock，阻止重复占用串口。
原终端启动脚本保持可用，但手驱动已由服务托管时会提示已运行，无需再次启动。

## 补丁与回滚

vendor_hashes.json 校验所依赖厂家文件。厂家更新后若校验不通过，应先审查补丁，不覆盖厂家新文件。
部署前状态保存在 deployment_baseline.json。
回滚：sudo python3 /home/dexforce/linkerhand/repos/w1_vr_glove_integration/rollback.py
回滚会停止本补丁管理的手套/手驱动/VR，移除本补丁服务链接和drop-in，恢复部署前启用状态及原VR/手服务运行状态。
原auto/act timer仅恢复开机启用状态，不在本次开机立即触发，以免切换当前机器人模式；下次开机按原模式运行。
不会删除采集数据、标定缓存或已有手套适配仓库。

## VR MCAP 录制（2026-09-29）

双侧握柄按住后，单击左摇杆按下按钮开始MCAP；再次单击停止保存。
松开任意一侧握柄也停止保存。启动尚未完成时松开，同样会停止，不留下后台录制。
开始/保存/失败由机器人扬声器播报；原VR录制状态和保存提示随MCAP真实结果更新。
数据默认保存在 /home/dexforce/collection_data/vr_glove/raw/episode_XXXXXX/raw/*.mcap。
话题和QoS沿用 w1_mcap_collection，缺少话题仍允许开始，并记入元数据。
不同时启动厂家JSON/JPEG录制。VR原删除接口暂不操作MCAP，也不会删除旧厂家数据。
X键手套功能不变。VR断开或超过3秒没有输入，停止本次VR拥有的录制。
同一时刻不允许VR接管已有终端录制；终端CLI入口仍保留。
VR退出时ExecStopPost清理仅针对 vr_mcap_owner.json 所标识的采集，不会自动创建新录制进程。

服务：linkerhand-w1-mcap.service。任务名：本目录mcap_settings.json。
这次MCAP补丁回滚入口：sudo python3 /home/dexforce/linkerhand/repos/w1_vr_glove_integration/rollback_mcap.py。
需先结束录制；要再撤销整套VR手套补丁，请先回滚MCAP，再运行原rollback.py。
