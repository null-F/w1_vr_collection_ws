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

默认 MCAP 记录 28 路（包含 `/imu/chassis` 与 `/imu/chassis/refined`）。完整分组见 [topics.yaml](topics.yaml)：原 30 路中，两路 CameraInfo 改为 device_info.json 去重元数据，两路原始 PointCloud2 默认不录。前后 RGB、深度及实体雷达继续记录。保留原始 ROS 消息供后续导出。

- 手action只记录 `/linkerhand/w1/ee/{left,right}/command`，位置0..100。手state来自 `/feedback/ee/{left,right}`。
- 不录制手套21通道原始输入、motor_cmd中间映射、厂家VR手指命令。
- 相机保存 `/camera/kfc_compressed` 原JPEG字节；已验证现场正常流为3840x1080左右拼接，录制元数据从现场消息读取尺寸。无图像时尺寸为null。
- 底盘前后深度默认启用。旧参数 collect_depth 仅为兼容保留。头部状态归入辅助组。
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

### 固定硬件设备信息与启动延迟

设备信息保存在 `runtime/device_snapshot.json`。常驻采集器启动时读取并校验缓存；
仅缓存缺失、格式不符或校验失败时获取一次现场快照。完整快照才会写入缓存，
跨录制、跨服务重启和跨机器人重启复用，不自动按时间过期。
开始录制只复制内存中的设备信息到该回合的 `device_info.json`，不再临时启动
快照进程。`snapshot_metadata` 记录来源、原始获取时间和是否已持久化；
关节名称和图像尺寸来自快照。头部标定另由常驻监听器按下述规则关联。

首次获取失败或信息不完整时仍允许录制，缺项记录到 warnings，且不把不完整信息
保存为永久缓存。之后每次按键不会重复等待，修复设备后可以在没有活动录制时执行：

```bash
bash /home/dexforce/linkerhand/repos/w1_mcap_collection/record.sh refresh
```

更换硬件或相机分辨率后可执行此命令刷新固定信息。刷新成功会原子更新缓存及
当前采集器的内存信息；失败保留原缓存并返回错误，不改写已有回合。

VR 周期状态查询优先读取属于当前采集进程的状态文件，并校验采集器和录制工作
进程身份，避免每次创建 ROS 客户端。恢复中、所有权待确认或状态异常时仍走原有
ROS 查询。此查询表示进程/回合状态，不代表 ROS 服务响应性检查；开始、停止、
取消仍通过原 ROS 服务执行并保留所有权校验、录制启动检查和 MCAP 保存校验。

### 首次安装或环境缺失时

`runtime/venvs` 不在 Git 中，拉取代码不会创建 Python 环境。确认没有活动录制后，
停止 `linkerhand-w1-mcap.service`，以 `dexforce` 用户在 PC1 执行：

```bash
bash /home/dexforce/linkerhand/repos/w1_mcap_collection/setup_env.sh
```

脚本使用系统 Python 3.10 创建 `--system-site-packages` 独立环境，并安装
`requirements.txt` 中的依赖。重复执行会复用已存在的合规环境，不清空目录，
也不会修改厂家 Python 环境或自动操作服务。系统需要提供 `venv`、ROS2 Humble、
PyYAML 和 Pillow；检查不通过时按错误补齐依赖，不使用全局 `pip install`。

离线安装可传入提前准备的、适用于 PC1 Python 3.10 / aarch64 的完整 wheel 目录：

```bash
bash /home/dexforce/linkerhand/repos/w1_mcap_collection/setup_env.sh \
  --no-index --find-links /path/to/wheels
```

只检查现有环境：

```bash
bash /home/dexforce/linkerhand/repos/w1_mcap_collection/check_env.sh
```

检查包含实际使用的 Python 模块、MCAP 版本、原生插件动态加载与 rosbag2 注册。
该检查不创建运行目录、不启动 ROS 节点、不发起录制、不改变服务状态。
Python `mcap` 包用于保存校验，原生 `rosbag2_storage_mcap` 插件用于录制，两者都需要。

检查通过后再启动采集服务，并确认不再反复重启。最终验收需短录制、停止保存、
MCAP 全量读回和进程收尾检查；同时检查 `coverage_status` / `missing_topics`，
环境检查通过本身不代表现场话题完整。

## 头部标定和转场质量检查

采集器在独立 ROS 执行器上监听 `/camera/kfc_calib_data`。每段 `device_info.json` 的 `head_calibration.versions` 按内容摘要保存原始 YAML 和相机序列号，`history` 记录首次关联、换版、无效、失流和恢复时间。连续 3 秒未收到广播后标记缺失；开始时不会将上次开机的缓存作为本段标定。兼容字段 `head_calibration_raw` 在本段首次获得有效标定后填写。时间字段是 PC1 接收或观察状态变化的时间。

单人模式会生成 `operator_events.jsonl`。结束后可用下列命令遍历所有 MCAP 分卷，按十路新增话题核对消息数、平均频率、最大间隔及各操作阶段的缺流。统计使用 MCAP 记录时钟。短段、低频话题和转场要结合目标频率判断。

```bash
cd /home/dexforce/linkerhand
runtime/venvs/mcap-collection/bin/python repos/w1_mcap_collection/audit_streams.py /home/dexforce/collection_data/vr_glove/raw/episode_000000
```

## 底盘传感器启动集成

在 PC1 使用厂家节点生成采集器订阅的数据。相机和雷达启动命令如下：

```bash
source /home/dexforce/.dex_env.sh
ros2 launch dexe_sensors_launch orbbec_nodes.launch.py
ros2 launch lidar_sensor dual_udp_lidar.launch
```

相机组独立发布 JPEG、原生深度、CameraInfo 和深度单位，雷达组发布两路实体扫描。两组由 `sensors.sh serve` 托管。点云在离线解析阶段生成。

安装服务后，启动 MCAP 服务会同时请求启动传感器服务。停止一段录制只关闭该段数据文件，传感器继续运行。开始录制前通过 check 核对十路都在接收；返回 0 表示测试窗口内每路至少收到一条，平均频率和最大间隔供现场判断。采集器仍允许缺流，并在 episode 中报告。

```bash
cd /home/dexforce/linkerhand
sudo systemctl link "$PWD/repos/w1_vr_glove_integration/linkerhand-w1-sensors.service"
sudo systemctl daemon-reload
sudo systemctl start linkerhand-w1-sensors.service
bash repos/w1_mcap_collection/sensors.sh check --seconds 30
journalctl -u linkerhand-w1-sensors.service -n 60 --no-pager
```

设置开机启动时执行 sudo systemctl enable linkerhand-w1-sensors.service linkerhand-w1-mcap.service。重启后再次运行 check 验证。首次从旧部署升级时，先保存活动录制，安装服务并 daemon-reload，再按需启动服务。

管理器先检查厂家同名节点，完整运行的一组会直接复用，存在部分相机节点时拒绝新增启动，避免重复打开设备。外部复用的进程由原服务管理，停止本服务只回收它自己启动的进程。启动后应持续保持同一运行模式；切换厂家自动/遥操模式前协调传感器服务，避免另一套启动脚本重复拉起节点。

现场曾出现 USB 控制器带宽不足。重新枚举 USB 是针对已确认设备的现场恢复操作，服务正常启动不自动执行。当前四组独立传感器服务若仍在运行，首次启动管理器会复用它们；需要统一移交时，在空闲状态停止旧的四组 w1-capture-* 用户服务，随后重新启动本服务，再运行 check。

## 采集开关与每段标定参数

编辑 `topics.yaml`：`continuous`、`command_or_event`、`static` 为候选话题；`disabled` 内的话题不进入 MCAP；`metadata_only` 当前支持 CameraInfo，不进入 MCAP，保存到每段 device_info.json。修改后在没有录制时重启 linkerhand-w1-mcap.service 生效。修改名单不停止传感器驱动，也不停止点云计算节点。

前后点云默认在 disabled 中，删除这两个条目或设 `disabled: []` 可恢复采集。recording_info 的 expected_topics/missing_topics 只按实际启用的 MCAP 清单计算，不会将主动关闭的点云误报为漏采。相机标定是否可用应查看 device_info 的元数据状态。

CameraInfo 保存路径为 `camera_info[topic].versions[sha256].parameters`，包括图像尺寸、frame_id、D/K/R/P、畸变模型、binning 与 ROI。Header stamp 不参与去重，相同参数只保留一份；变更或断流用 history 记录，不逐帧写盘。新导出流程需从此处读取相机参数；旧包里的 CameraInfo 仍位于 MCAP。

手柄外参保存在 `controller_mounting_extrinsics`：`configured` 为开录时配置文件快照，`effective` 为通过 VR 进程身份验证的已加载参数；包含文件 SHA256、米单位平移、固定轴 xyz 度旋转及右乘约定。`runtime_verified=false` 时不会冒充已确认的运行参数，effective 为 null，并记录警告。

VR 每次加载 offsets 时写入 `/run/linkerhand-w1-pedals/controller_offsets.json`，包含 PID、启动时间和 boot ID。首次部署该增强后需在安全时重新加载 VR 服务，之后每段采集可验证实际加载值；仅改配置文件未重新加载时会同时保存文件值和运行值并标记不一致。既有 episode 不会被回写。

### IMU 与 odom 开机启动

PC1 使用 `linkerhand-w1-imu.service` 运行 `imu_watchdog.py`。脚本等待
`/dev/ttyIMU`，复用已运行的厂家 `imu/talker`；若没有实例则启动厂家原始
驱动，进程退出后每两秒检查重启。停止服务只结束自身启动的驱动。
该服务不修改底盘 IMU 融合参数，也不重启底盘控制服务。

安装（PC1，工程位于 `/home/dexforce/linkerhand`）：

```bash
sudo install -m 644 ~/linkerhand/repos/w1_vr_glove_integration/linkerhand-w1-imu.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now linkerhand-w1-imu.service
systemctl status linkerhand-w1-imu.service
```

验证 `/imu/chassis` 与 `/feedback/odom` 必须实际收到消息，不能只检查话题名。
厂家自动/建图/标定模式也可能启动 IMU；此脚本只会在自身启动前检查现有实例，
无法阻止厂家脚本随后启动重复实例，切换这些模式时需统一驱动所有权。
服务已启用不等于已完成断电冷启动验证；仍需在下次开机后复查两路消息。
