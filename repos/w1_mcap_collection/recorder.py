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
from pathlib import Path
import yaml
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rclpy.qos import qos_profile_sensor_data
from std_srvs.srv import Trigger
from engine import Engine
from device_snapshot import DeviceSnapshot
from storage import atomic_json, process_identity

HERE=Path(__file__).resolve().parent
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
        self.declare_parameter('collect_depth',False)  # compatibility only: no depth hardware in this profile
        self.engine=Engine(RUNTIME)
        self.config=yaml.safe_load((HERE/'topics.yaml').read_text())
        self.device_snapshot=DeviceSnapshot(RUNTIME/'device_snapshot.json',capture_device_snapshot)
        self.get_logger().info('Device snapshot: '+json.dumps(self.device_snapshot.describe()))
        self.engine.persist()  # Publish the current recorder identity for read-only status.
        for name,callback in [('start_recording',self.start),('stop_recording',self.stop),('cancel_recording',self.cancel),('status',self.status),('refresh_snapshot',self.refresh_snapshot)]:
            self.create_service(Trigger,'~/'+name,self.wrap(callback))
        self.create_timer(.5,self.poll)

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

    def start(self):
        topics=sum([self.config[k] for k in ['continuous','command_or_event','static']],[])
        if self.get_parameter('collect_auxiliary').value:topics+=self.config['optional']
        warnings=[]
        if self.get_parameter('collect_depth').value:warnings.append('collect_depth ignored: W1 profile has no wrist/depth stream')
        for t in topics:
            if not self.get_publishers_info_by_topic(t):warnings.append(f'{t}: no publisher at start')
        snap,snapshot_warnings=self.device_snapshot.for_episode()
        warnings.extend(snapshot_warnings)
        snap.update(device={'id':'w1-pc1','type':'Dexforce W1'},
                    hand={'model':'Linker_L6','dof':6,'position_unit':'normalized_0_100',
                          'action_topics':['/linkerhand/w1/ee/left/command','/linkerhand/w1/ee/right/command'],
                          'state_topics':['/feedback/ee/left','/feedback/ee/right']},
                    topic_groups=self.config,warnings=warnings)
        return self.engine.start(str(self.get_parameter('task_name').value).strip(),
                                 str(self.get_parameter('data_root').value),topics,snap,warnings)

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
            if node is not None:node.destroy_node()
            if rclpy.ok():rclpy.shutdown()
            lock.close()

if __name__=='__main__':main()
