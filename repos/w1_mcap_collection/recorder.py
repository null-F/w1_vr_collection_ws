#!/usr/bin/env python3
"""Resident W1 collector. Missing streams are warnings; no robot control APIs."""
from __future__ import annotations
import fcntl
import io
import json
import os
import signal
import subprocess
import sys
import time
import threading
from pathlib import Path
import yaml
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.qos import qos_profile_sensor_data
from std_srvs.srv import Trigger
from engine import Engine
from device_snapshot import DeviceSnapshot, HeadCalibration
from capture_settings import select_topics, mounting_snapshot, camera_parameters
from storage import atomic_json, process_identity, read_json

HERE=Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'w1_vr_glove_integration'))
from operator_state import settings
from operator_journal import begin_episode

RUNTIME=Path(os.environ.get('W1_MCAP_RUNTIME','/home/dexforce/linkerhand/runtime'))
DATA_ROOT=os.environ.get('W1_MCAP_DATA_ROOT','/home/dexforce/collection_data')


def capture_device_snapshot():
    result=subprocess.run([sys.executable,str(HERE/'recorder.py'),'snapshot'],
                          capture_output=True,text=True,timeout=8)
    if result.returncode:
        raise RuntimeError('Device snapshot failed: '+result.stderr[-300:])
    return json.loads(result.stdout)


class Recorder(Node):
    def __init__(self):
        super().__init__('w1_mcap_recorder')
        self.declare_parameter('task_name','');self.declare_parameter('data_root',DATA_ROOT)
        self.declare_parameter('collect_auxiliary',False)
        self.declare_parameter('collect_depth',False)  # backward-compatible parameter
        self.operator_mode = settings()['mode']
        self.calibration = HeadCalibration()
        self.engine=Engine(RUNTIME, self.calibration)
        self.config=yaml.safe_load((HERE/'topics.yaml').read_text())
        _, self.calibration.camera_topics = select_topics(self.config)
        self.device_snapshot=DeviceSnapshot(RUNTIME/'device_snapshot.json',capture_device_snapshot)
        self.get_logger().info('Device snapshot: '+json.dumps(self.device_snapshot.describe()))
        if self.engine.active:
            path = Path(self.engine.active['episode_dir']) / 'device_info.json'
            if path.is_file():
                metadata = json.loads(path.read_text())
                if 'head_calibration' in metadata:
                    self.calibration.attach(path, metadata)
        self.engine.persist()  # Publish the current recorder identity for read-only status.
        for name,callback in [('start_recording',self.start),('stop_recording',self.stop),('cancel_recording',self.cancel),('status',self.status),('refresh_snapshot',self.refresh_snapshot)]:
            self.create_service(Trigger,'~/'+name,self.wrap(callback))
        self.create_service(Trigger, '~/pedal_start', self.wrap(self.pedal_start))
        self.create_service(Trigger, '~/pedal_stop', self.wrap(self.pedal_stop))
        self.create_service(Trigger, '~/vr_start', self.wrap(self.vr_start))
        self.create_service(Trigger, '~/vr_stop', self.wrap(lambda: self.vr_end(False)))
        self.create_service(Trigger, '~/vr_cancel', self.wrap(lambda: self.vr_end(True)))
        self.create_timer(.5,self.poll)
        # Start/stop services can block on the bag process. Observe camera changes independently.
        from std_msgs.msg import String
        self.cal_node = Node('w1_head_calibration_monitor', use_global_arguments=False)
        self.cal_node.create_subscription(String, '/camera/kfc_calib_data',
                                          lambda m: self.calibration.observe(m.data), 10)
        from sensor_msgs.msg import CameraInfo
        for topic in self.calibration.camera_topics:
            def observe_camera(message, topic=topic):
                try:
                    self.calibration.observe_camera_info(topic, camera_parameters(message))
                except (ValueError, TypeError) as exc:
                    self.get_logger().warning('Invalid camera parameters '+topic+': '+str(exc))
            self.cal_node.create_subscription(CameraInfo, topic, observe_camera, qos_profile_sensor_data)
        self.cal_node.create_timer(.5, self.calibration.tick)
        self.cal_executor = SingleThreadedExecutor()
        self.cal_executor.add_node(self.cal_node)
        self.cal_thread = threading.Thread(target=self.cal_spin, daemon=True)
        self.cal_thread.start()

    def cal_spin(self):
        try:
            self.cal_executor.spin()
        except ExternalShutdownException:
            pass

    def close_monitor(self):
        self.cal_executor.shutdown()
        self.cal_thread.join()
        self.cal_node.destroy_node()

    def vr_start(self):
        if self.operator_mode != 'dual':
            raise RuntimeError('VR recording buttons are disabled in single-operator mode')
        intent = read_json(RUNTIME/'vr_mcap_owner.json', {})
        if not intent.get('token') or intent.get('episode_dir'):
            raise RuntimeError('Missing pending VR recording request')
        return self.start(source='vr', task=intent['task'], token=intent['token'])

    def vr_end(self, cancel):
        active = self.engine.active or {}
        owner = read_json(RUNTIME/'vr_mcap_owner.json', {})
        if (active.get('source') not in (None, 'vr') or not owner.get('episode_dir')
                or owner['episode_dir'] != active.get('episode_dir')
                or (active.get('source') == 'vr' and owner.get('token') != active.get('request_token'))):
            raise RuntimeError('Active recording does not match VR ownership')
        return self.cancel() if cancel else self.stop()

    def pedal_start(self):
        if self.operator_mode != 'single':
            raise RuntimeError('Single-operator mode is disabled')
        task = json.loads((HERE.parent / 'w1_vr_glove_integration/mcap_settings.json').read_text())['task_name']
        return self.start(source='pedal', task=task)

    def pedal_stop(self):
        if self.operator_mode != 'single' or (self.engine.active or {}).get('source') != 'pedal':
            raise RuntimeError('Active recording is not pedal-owned')
        return self.stop()

    def wrap(self,fn):
        def callback(req,response):
            try:
                value=fn();response.success=value.get('save_status')!='failed'
            except Exception as exc:
                response.success=False;value={'error':str(exc),'state':self.engine.status()}
                self.get_logger().error(str(exc))
            response.message=json.dumps(value,ensure_ascii=False)
            return response
        return callback

    def poll(self):
        try:self.engine.poll()
        except Exception as exc:self.get_logger().error(f'Recorder monitoring failed: {exc}')

    def start(self, source='manual', task=None, token=None):
        topics, metadata_topics = select_topics(self.config, self.get_parameter('collect_auxiliary').value)
        warnings=[]
        if self.get_parameter('collect_depth').value:warnings.append('collect_depth is legacy: front/rear depth are included by default')
        for t in topics:
            if not self.get_publishers_info_by_topic(t):warnings.append(f'{t}: no publisher at start')
        snap,snapshot_warnings=self.device_snapshot.for_episode()
        warnings.extend(snapshot_warnings)
        mounting, mounting_warnings = mounting_snapshot(HERE.parents[1]/'config/w1/controller_offsets.json',
                            Path('/run/linkerhand-w1-pedals/controller_offsets.json'))
        warnings.extend(mounting_warnings)
        snap['controller_mounting_extrinsics'] = mounting
        snap['capture_selection'] = dict(recorded_topics=topics, metadata_only_topics=metadata_topics,
                                        disabled_topics=list(self.config.get('disabled', [])))
        snap.update(device={'id':'w1-pc1','type':'Dexforce W1'},
                    hand={'model':'Linker_L6','dof':6,'position_unit':'normalized_0_100',
                          'action_topics':['/linkerhand/w1/ee/left/command','/linkerhand/w1/ee/right/command'],
                          'state_topics':['/feedback/ee/left','/feedback/ee/right']},
                    topic_groups=self.config,warnings=warnings)
        stage = begin_episode() if self.operator_mode == 'single' else None
        return self.engine.start(task or str(self.get_parameter('task_name').value).strip(),
                                 str(self.get_parameter('data_root').value),topics,snap,warnings,source,stage,token)

    def stop(self):
        if not self.engine.active:raise RuntimeError('Not recording; use status for the previous result')
        return self.engine.finalize('stop')

    def cancel(self):
        if not self.engine.active:raise RuntimeError('Not recording')
        return self.engine.finalize('cancel',cancel=True)

    def status(self):
        self.engine.poll();return self.engine.status()

    def refresh_snapshot(self):
        if self.engine.active:
            raise RuntimeError('Cannot refresh device snapshot while recording')
        return {'snapshot':self.device_snapshot.refresh()}


def snapshot_main():
    from sensor_msgs.msg import JointState,CompressedImage
    from std_msgs.msg import String
    from PIL import Image
    rclpy.init(args=[]);node=Node('w1_mcap_snapshot');got={}
    def image_cb(m):
        if 'head_stereo' in got:return
        try:
            im=Image.open(io.BytesIO(bytes(m.data)))
            got['head_stereo']={'topic':'/camera/kfc_compressed','message_type':'sensor_msgs/msg/CompressedImage',
                'encoding':m.format,'width':im.width,'height':im.height,'layout':'left_right_side_by_side',
                'per_eye_width':im.width//2,'per_eye_height':im.height,'observed_time_ns':time.time_ns()}
        except Exception as exc:got['image_snapshot_error']=str(exc)
    subs=[node.create_subscription(JointState,'/feedback/joint',lambda m:got.setdefault('body_joint_names',list(m.name)),qos_profile_sensor_data),
          node.create_subscription(String,'/camera/kfc_calib_data',lambda m:got.setdefault('head_calibration_raw',m.data),qos_profile_sensor_data),
          node.create_subscription(CompressedImage,'/camera/kfc_compressed',image_cb,qos_profile_sensor_data)]
    end=time.monotonic()+2.5
    try:
        while time.monotonic()<end and not all(k in got for k in ['head_stereo','head_calibration_raw','body_joint_names']):rclpy.spin_once(node,timeout_sec=.1)
        if 'head_stereo' not in got:got['head_stereo']={'topic':'/camera/kfc_compressed','width':None,'height':None,'observed':False}
        print(json.dumps(got))
    finally:
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()


def main():
    if len(sys.argv)>1 and sys.argv[1]=='snapshot':snapshot_main();return
    if len(sys.argv)>1 and sys.argv[1]=='serve':sys.argv.pop(1)
    RUNTIME.mkdir(parents=True,exist_ok=True)
    lock=(RUNTIME/'mcap_recorder.serve.lock').open('w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('A collector already owns this runtime directory')
    rclpy.init();node=None;exit_reason='shutdown'
    try:
        node=Recorder();atomic_json(RUNTIME/'mcap_recorder.pid',{'identity':process_identity(os.getpid()),'script':str(HERE/'recorder.py'),'node':node.get_fully_qualified_name()})
        rclpy.spin(node)
    except (KeyboardInterrupt,ExternalShutdownException):pass
    except BaseException:
        exit_reason='exception';raise
    finally:
        try:
            if node is not None and node.engine.active:node.engine.finalize(exit_reason)
        finally:
            if node is not None:
                node.close_monitor()
                node.destroy_node()
            if rclpy.ok():rclpy.shutdown()
            lock.close()

if __name__=='__main__':main()
