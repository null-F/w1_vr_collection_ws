# W1 MCAP collection

ROS2 Humble / PC1。仅采集，不发布运动命令，不改厂家源码。

## 终端使用

在 PC1（dexforce@192.168.20.20）运行：

```bash
bash /home/dexforce/linkerhand/repos/w1_mcap_collection/record.sh start pick_object
bash /home/dexforce/linkerhand/repos/w1_mcap_collection/record.sh status
bash /home/dexforce/linkerhand/repos/w1_mcap_collection/record.sh stop
```

`start` 会按需启动常驻采集管理程序，`stop` 关闭当前 MCAP 并校验保存结果。后台管理程序保持运行，不影响机器人遥操。

`cancel` 停止并删除当前 episode，仅在明确要丢弃当前采集时使用：

```bash
bash /home/dexforce/linkerhand/repos/w1_mcap_collection/record.sh cancel
```

默认路径保留同事原有约定：

```text
/home/dexforce/collection_data/<task>/raw/episode_000000/
  raw/metadata.yaml
  raw/raw_0.mcap            # 实际MCAP文件名由rosbag2生成
  episode.json
  device_info.json
  recording_info.json
  record.log
  worker_result.json
```

首次启动常驻进程前可以设置 `W1_MCAP_DATA_ROOT`，或者通过ROS参数 `data_root` 设置后续episode目录。不会迁移已有数据。

## 与 VR / 手套配合

采集器不会自动切换控制来源。组合遥操依次准备：

1. 机器人静止、手上电、两只手套使用已验证的两个独立USB口。
2. PC1终端1：`bash /home/dexforce/linkerhand/repos/w1_glove_integration/start_hands.sh`。使用独立手驱动和专用话题，停止原厂家手服务。
3. PC1终端2：`bash /home/dexforce/linkerhand/repos/w1_glove_integration/start_gloves.sh`。按原程序提示完成双手标定。
4. 启动厂家VR遥操模式；若VR已经运行则无需重复启动。VR控制本体，手套控制双手。组合模式期间不运行原厂家run_ee.sh或重启dexe-devices.service。
5. PC1另一个终端运行采集start/stop。停止采集不会停止VR或手套。

## 数据范围

详见 topics.yaml。默认包括本体state/action、左右手最终action与真实state、底盘指令和反馈、头部双目JPEG与标定、VR位姿、TF和模式。

- 手action只记录 `/linkerhand/w1/ee/{left,right}/command`，位置0..100。手state来自 `/feedback/ee/{left,right}`。
- 不录制手套21通道原始输入、motor_cmd中间映射、厂家VR手指命令。
- 相机保存 `/camera/kfc_compressed` 原JPEG字节；已验证现场正常流为3840x1080左右拼接，录制元数据从现场消息读取尺寸。无图像时尺寸为null。
- 不录腕部相机、深度或低分辨率preview。旧collect_depth=true仅报告忽略，不订阅不存在的腕部。
- 可选辅助话题通过 `collect_auxiliary` 参数启用。
- 原Header时间戳保留；无Header接口以rosbag接收时间索引。采集不重采样、不伪造零值。

## 保存结果与缺流分开

允许缺少话题、没有publisher或零消息。正常关闭且MCAP校验通过，返回 success=true / save_status=saved；缺流列入 missing_topics，coverage_status=partial。零消息可能是静态、按事件或未启用，不能只据此认定硬件故障。

写盘失败、关闭失败、metadata/MCAP不一致返回 success=false / save_status=failed，并保留文件和日志。终端命令失败会返回非零退出码。

停止时验证范围：MCAP footer、ROS schema、summary计数、metadata计数，以及首尾消息可读性。不是每次stop都全量扫描所有图像。验收测试额外执行全量读回。

## 生命周期

常驻进程和启动入口分别加锁。常驻程序正常退出或SIGTERM会收尾。独立看护进程检测父进程消失（包括父进程SIGKILL），请求rosbag2通过SIGINT关闭。只有经过PID、启动时间、boot ID、UID验证的录制进程会被停止，不使用宽泛pkill。

下次启动读取持久状态并检查未完成任务，不静默重复开录。断电、磁盘硬故障或同时强杀看护和rosbag不能保证文件完整，会按残留状态报告失败。失败episode不自动删除。

## 部署与依赖

- 厂家ROS环境 `/home/dexforce/.dex_env.sh`；独立MCAP插件在 runtime/mcap_prefix。
- 独立Python环境 `/home/dexforce/linkerhand/runtime/venvs/mcap-collection`，使用系统ROS库和mcap==1.5.0，不覆盖厂家Python包。
- 测试专用环境变量：W1_MCAP_RUNTIME、W1_MCAP_DOMAIN_ID、W1_MCAP_DATA_ROOT。生产默认域20；验证域79与真机隔离。
- 常驻日志：`/home/dexforce/linkerhand/runtime/logs/mcap_recorder.log`。
