#!/usr/bin/env python3
"""Use the existing recorder under its CLI lock, tracking only VR-owned episodes."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import time
import uuid
CORE=Path('/home/dexforce/linkerhand/repos/w1_mcap_collection')
RUNTIME=Path('/home/dexforce/linkerhand/runtime')
OWNER=RUNTIME/'vr_mcap_owner.json'
sys.path.insert(0,str(CORE))
import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger
from rcl_interfaces.srv import SetParameters
from rcl_interfaces.msg import Parameter,ParameterValue,ParameterType
from storage import read_json,atomic_json,identity_alive
from cli import wait_future


def brief(value):
    keys=['phase','recording','episode_dir','save_status','coverage_status','total_messages','duration_sec','errors','error','missing_topics','warnings']
    return {k:value[k] for k in keys if k in value}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['start','stop','cancel','status']);parser.add_argument('--task');a=parser.parse_args()
    if a.command in ('stop','cancel') and not OWNER.exists():
        print(json.dumps({'success':True,'result':{'save_status':'not_owned'}}));return 0
    node=None
    with (RUNTIME/'mcap_recorder.launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        pid=read_json(RUNTIME/'mcap_recorder.pid',{})
        if not isinstance(pid,dict) or not identity_alive(pid.get('identity')):raise RuntimeError('MCAP resident is unavailable; no new process was launched')
        script=(Path('/proc')/str(pid['identity']['pid'])/'cmdline').read_bytes().split(b'\0')
        if str(CORE/'recorder.py').encode() not in script:raise RuntimeError('Recorder identity mismatch')
        target=pid.get('node')
        if target!='/w1_mcap_recorder':raise RuntimeError('Unexpected recorder node')
        rclpy.init(args=[]);node=Node('vr_mcap_client_'+str(os.getpid()))
        def call(service):
            c=node.create_client(Trigger,target+'/'+service)
            try:
                if not c.wait_for_service(timeout_sec=5):raise RuntimeError('Recorder service unavailable')
                response=wait_future(node,c.call_async(Trigger.Request()),90)
                return response.success,json.loads(response.message)
            finally:node.destroy_client(c)
        try:
            ok,state=call('status')
            if not ok:raise RuntimeError(str(state))
            owner=read_json(OWNER,{})
            # Recover an interrupted start while still holding the same CLI lock.
            if owner and not owner.get('episode_dir'):
                runtime=read_json(RUNTIME/'mcap_recorder_state.json',{})
                candidate=runtime.get('active') or runtime.get('last_result') or {}
                episode=candidate.get('episode_dir','')
                if (episode and Path(episode).parent.parent.name==owner.get('task')
                    and candidate.get('started_wall_ns',0)>=owner.get('requested_ns',0)):
                    owner['episode_dir']=episode;atomic_json(OWNER,owner)
            owned=owner.get('episode_dir') if owner else None
            if a.command=='status':
                result=brief(state);result['last_result']=brief(state.get('last_result') or {})
                result['owned_episode']=owned;result['owner_pending']=bool(owner and not owned)
                print(json.dumps({'success':True,'result':result},ensure_ascii=False));return 0
            if a.command=='start':
                if state.get('recording'):raise RuntimeError('An episode is already active; VR did not take ownership')
                if owner:raise RuntimeError('An earlier VR episode needs cleanup before a new start')
                settings=read_json(Path(__file__).with_name('mcap_settings.json'),{})
                task=a.task or settings.get('task_name','vr_glove')
                c=node.create_client(SetParameters,target+'/set_parameters')
                if not c.wait_for_service(timeout_sec=5):raise RuntimeError('Recorder parameter service unavailable')
                req=SetParameters.Request();req.parameters=[Parameter(name='task_name',value=ParameterValue(type=ParameterType.PARAMETER_STRING,string_value=task))]
                response=wait_future(node,c.call_async(req),10)
                if not all(v.successful for v in response.results):raise RuntimeError('Task parameter rejected')
                atomic_json(OWNER,{'token':uuid.uuid4().hex,'task':task,'requested_ns':time.time_ns(),'episode_dir':None})
                ok,result=call('start_recording')
                if ok and result.get('episode_dir'):
                    owner=read_json(OWNER,{});owner['episode_dir']=result['episode_dir'];atomic_json(OWNER,owner)
                print(json.dumps({'success':ok,'result':brief(result)},ensure_ascii=False));return 0 if ok else 1
            if not owner:
                result={'save_status':'not_owned'};ok=True
            elif state.get('recording'):
                if not owned or state.get('episode_dir')!=owned:raise RuntimeError('Active episode is not owned by VR; refusing to stop it')
                ok,result=call('cancel_recording' if a.command=='cancel' else 'stop_recording')
                if result.get('episode_dir')==owned and result.get('save_status') in ['saved','failed','cancelled']:OWNER.unlink(missing_ok=True)
            else:
                last=state.get('last_result') or {}
                if owned and last.get('episode_dir')==owned:
                    result=brief(last)
                    ok=result.get('save_status')==('cancelled' if a.command=='cancel' else 'saved')
                else:
                    result={'save_status':'not_recording','error':'No matching active VR episode'};ok=False
                OWNER.unlink(missing_ok=True)
            print(json.dumps({'success':ok,'result':brief(result)},ensure_ascii=False));return 0 if ok else 1
        finally:
            if node is not None:node.destroy_node()
            if rclpy.ok():rclpy.shutdown()

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'success':False,'error':str(exc)},ensure_ascii=False));raise SystemExit(1)
