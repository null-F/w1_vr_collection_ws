#!/usr/bin/env python3
"""ROS service client with explicit shell failure codes and serialized launch."""
import argparse
import fcntl
import json
import os
import subprocess
import time
from pathlib import Path
import rclpy
from rclpy.node import Node
from rcl_interfaces.srv import SetParameters
from rcl_interfaces.msg import Parameter,ParameterValue,ParameterType
from std_srvs.srv import Trigger
from storage import read_json,identity_alive

HERE=Path(__file__).resolve().parent
RUNTIME=Path(os.environ.get('W1_MCAP_RUNTIME','/home/dexforce/linkerhand/runtime'))


def wait_future(node,future,timeout):
    rclpy.spin_until_future_complete(node,future,timeout_sec=timeout)
    if not future.done():raise RuntimeError('Service timeout; inspect recorder status/log before retrying')
    return future.result()


def ensure_server(client,target):
    pid_data=read_json(RUNTIME/'mcap_recorder.pid',{})
    if isinstance(pid_data,int):
        if Path('/proc',str(pid_data)).exists():raise RuntimeError('Legacy resident collector is running; stop the old collector before upgrade')
        pid_data={}
    live=identity_alive(pid_data.get('identity'))
    if live:
        expected=str(HERE/'recorder.py')
        cmd=(Path('/proc')/str(pid_data['identity']['pid'])/'cmdline').read_bytes().split(b'\0')
        if expected.encode() not in cmd:raise RuntimeError('Resident PID script mismatch')
        if pid_data.get('node') != target:raise RuntimeError('Runtime directory belongs to a different node')
    else:
        (RUNTIME/'logs').mkdir(parents=True,exist_ok=True)
        with (RUNTIME/'logs/mcap_recorder.log').open('a') as f:
            proc=subprocess.Popen(['bash',str(HERE/'serve.sh'),'--ros-args','-r','__node:='+target.strip('/')],
                                  stdout=f,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
        end=time.monotonic()+15
        while time.monotonic()<end:
            if proc.poll() is not None:raise RuntimeError('Collector startup failed; inspect runtime/logs/mcap_recorder.log')
            if client.wait_for_service(timeout_sec=.5):return
        raise RuntimeError('Collector service did not become ready')
    if not client.wait_for_service(timeout_sec=10):raise RuntimeError('Collector process exists but service is unavailable')


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['start','stop','cancel','status']);p.add_argument('task',nargs='?')
    p.add_argument('--node',default='w1_mcap_recorder');a=p.parse_args()
    if a.command=='start' and not a.task:p.error('start requires a task name')
    target='/'+a.node.strip('/')
    if '/' in target[1:]:p.error('node must be a simple node name')
    RUNTIME.mkdir(parents=True,exist_ok=True)
    with (RUNTIME/'mcap_recorder.launch.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        rclpy.init(args=[]);n=Node('w1_mcap_client_'+str(os.getpid()))
        try:
            svc={'start':'start_recording','stop':'stop_recording','cancel':'cancel_recording','status':'status'}[a.command]
            client=n.create_client(Trigger,target+'/'+svc);ensure_server(client,target)
            if a.command=='start':
                param=n.create_client(SetParameters,target+'/set_parameters')
                if not param.wait_for_service(timeout_sec=5):raise RuntimeError('Parameter service unavailable')
                req=SetParameters.Request();req.parameters=[Parameter(name='task_name',value=ParameterValue(type=ParameterType.PARAMETER_STRING,string_value=a.task))]
                result=wait_future(n,param.call_async(req),10)
                if not all(x.successful for x in result.results):raise RuntimeError('Task parameter rejected')
            result=wait_future(n,client.call_async(Trigger.Request()),90)
            try:value=json.loads(result.message)
            except ValueError:value={'message':result.message}
            # Detailed counts/config remain in recording_info.json. Keep terminal output concise.
            if a.command in ('stop','cancel'):
                value={k:value[k] for k in ['save_status','coverage_status','episode_dir','total_messages','duration_sec','missing_topics','errors','error'] if k in value}
            print(json.dumps({'success':result.success,'result':value},ensure_ascii=False,indent=2))
            return 0 if result.success else 1
        except Exception as exc:
            print(json.dumps({'success':False,'error':str(exc)},ensure_ascii=False));return 1
        finally:
            n.destroy_node()
            if rclpy.ok():rclpy.shutdown()

if __name__=='__main__':raise SystemExit(main())
