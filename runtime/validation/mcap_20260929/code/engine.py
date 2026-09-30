"""Episode lifecycle for one resident recorder; only owns spawned recording processes."""
from __future__ import annotations
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from storage import atomic_json, read_json, process_identity, identity_alive, signal_identity, validate_bag, file_result

HERE=Path(__file__).resolve().parent


def valid_task(task):
    return bool(task and len(task)<=80 and all(c.isalnum() or c in '-_' for c in task))


class Engine:
    def __init__(self, runtime):
        self.runtime=Path(runtime);self.runtime.mkdir(parents=True,exist_ok=True)
        self.state_file=self.runtime/'mcap_recorder_state.json'
        self.active=None;self.proc=None;self.log_handle=None;self.last_result=None
        previous=read_json(self.state_file,{})
        if previous.get('active'):
            if previous.get('version')!=2:raise RuntimeError('Legacy recording state requires manual inspection; refusing duplicate recorder')
            self.active=previous['active'];self.phase='recovering'
        else:
            self.phase=previous.get('phase','idle');self.last_result=previous.get('last_result')
            if previous.get('pid'):raise RuntimeError('Legacy recorder PID state found; inspect before restart')

    def persist(self):
        atomic_json(self.state_file,{'version':2,'owner':process_identity(os.getpid()),'phase':self.phase,
                                    'active':self.active,'last_result':self.last_result})

    def status(self):
        return {'phase':self.phase,'recording':bool(self.active), 'episode_dir':self.active['episode_dir'] if self.active else None,
                'last_result':self.last_result}

    def start(self,task,data_root,topics,snapshot,warnings):
        self.poll()
        if self.active:raise RuntimeError('A recording or recovery is already active')
        if not valid_task(task):raise ValueError('task_name must be 1-80 letters/digits/_/-')
        root=Path(data_root).expanduser().resolve();raw=root/task/'raw';raw.mkdir(parents=True,exist_ok=True)
        nums=[int(p.name[8:]) for p in raw.glob('episode_*') if p.is_dir() and p.name[8:].isdigit()]
        episode=raw/f'episode_{max(nums,default=-1)+1:06d}';episode.mkdir(exist_ok=False)
        session={'episode_dir':str(episode),'data_root':str(root),'task':task,'id':uuid.uuid4().hex,
                 'started_wall_ns':time.time_ns(),'topics':topics,'warnings':warnings,
                 'owner':process_identity(os.getpid()),'worker':None}
        self.active=session;self.phase='starting'
        try:
            atomic_json(episode/'episode.json',session)
            atomic_json(episode/'device_info.json',snapshot)
            self.persist()
            command=['ros2','bag','record','-s','mcap','-o',str(episode/'raw'),
                     '--include-unpublished-topics','--qos-profile-overrides-path',str(HERE/'qos_overrides.yaml'),
                     '--max-cache-size','134217728',*topics]
            self.log_handle=(episode/'record.log').open('w',encoding='utf-8')
            self.proc=subprocess.Popen([sys.executable,str(HERE/'record_worker.py'),
                '--parent',str(episode/'episode.json'),'--result',str(episode/'worker_result.json'),
                '--child-state',str(episode/'child_process.json'),'--',*command],
                start_new_session=True,stdin=subprocess.DEVNULL,stdout=self.log_handle,stderr=subprocess.STDOUT)
            session['worker']=process_identity(self.proc.pid);self.persist()
            time.sleep(1)
            if self.proc.poll() is not None:
                self.finalize('startup_failure')
                raise RuntimeError(f'Recorder exited during startup; inspect {episode}/record.log')
            self.phase='recording';self.persist()
            return {'episode_dir':str(episode),'warnings':warnings,'message':'Recording started; missing streams are allowed'}
        except Exception:
            if self.active:self.finalize('startup_failure')
            raise

    def _child(self):
        return read_json(Path(self.active['episode_dir'])/'child_process.json') if self.active else None

    def poll(self):
        if not self.active:return
        if self.proc is not None:self.proc.poll()  # reap a completed worker
        if not identity_alive(self.active.get('worker')):
            self.finalize('recovery' if self.phase=='recovering' else 'unexpected_exit')

    def finalize(self,reason='stop',cancel=False):
        if not self.active:return self.last_result
        s=self.active;episode=Path(s['episode_dir']);worker=s.get('worker');self.phase='finalizing'
        cleanup_errors=[]
        try:
            signal_identity(worker,signal.SIGINT)
            end=time.monotonic()+32
            while identity_alive(worker) and time.monotonic()<end:
                if self.proc is not None:self.proc.poll()
                time.sleep(.1)
            if identity_alive(worker):
                cleanup_errors.append('Recorder worker exceeded shutdown deadline')
                signal_identity(worker,signal.SIGKILL)
            # A killed worker may have left a separate rosbag group. Only signal the verified identity.
            child=self._child()
            if identity_alive(child):
                cleanup_errors.append('Orphan rosbag required recovery')
                for sig,seconds in [(signal.SIGINT,20),(signal.SIGTERM,5),(signal.SIGKILL,3)]:
                    signal_identity(child,sig,group=True);end=time.monotonic()+seconds
                    while identity_alive(child) and time.monotonic()<end:time.sleep(.1)
                    if not identity_alive(child):break
            if self.proc is not None:
                try:self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:cleanup_errors.append('Worker did not reap')
            if identity_alive(worker) or identity_alive(child):
                self.phase='cleanup_failed';self.persist()
                raise RuntimeError('Verified recording process remains alive; refusing a new episode')
        finally:
            if self.log_handle is not None:self.log_handle.close();self.log_handle=None
        validation=validate_bag(episode/'raw',s['topics'])
        result=file_result(validation,read_json(episode/'worker_result.json'),reason)
        result.update(episode_dir=str(episode),started_wall_ns=s['started_wall_ns'],finished_wall_ns=time.time_ns(),
                      warnings=s.get('warnings',[]),expected_topics=s['topics'])
        if cleanup_errors:result['errors'].extend(cleanup_errors);result['save_status']='failed'
        self.active=None;self.proc=None
        self.phase='saved' if result['save_status']=='saved' else 'failed'
        if cancel:
            import shutil
            root=Path(s['data_root']).resolve();p=episode.resolve()
            if not p.is_relative_to(root) or not p.name.startswith('episode_') or p.parent.name!='raw':
                raise RuntimeError('Refusing cancel outside the managed episode')
            if read_json(p/'episode.json',{}).get('id')!=s['id']:raise RuntimeError('Episode identity mismatch')
            shutil.rmtree(p);self.phase='cancelled';result['save_status']='cancelled'
        else:
            try:atomic_json(episode/'recording_info.json',result)
            except OSError as exc:
                result['errors'].append(f'Cannot write recording_info: {exc}');result['save_status']='failed';self.phase='failed'
        self.last_result=result
        self.persist()
        return result
