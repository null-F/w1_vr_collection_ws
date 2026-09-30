import json,os,pathlib,subprocess,sys,time,signal
root=pathlib.Path('/home/dexforce/linkerhand/runtime/validation/mcap_20260929')
assert os.environ['ROS_DOMAIN_ID']=='79'
runtime=pathlib.Path(os.environ['W1_MCAP_RUNTIME']);code=root/'code';results=[]
publisher_code='''import os,time,rclpy,io
assert os.environ['ROS_DOMAIN_ID']=='79'
from rclpy.node import Node
from rclpy.qos import QoSProfile,DurabilityPolicy
from sensor_msgs.msg import JointState,CompressedImage
from std_msgs.msg import String
from end_effector_interfaces.msg import EEFeedback,EEJointState,EEJointControl
from PIL import Image
rclpy.init();n=Node('w1_collection_synthetic_only');publishers=[]
def add(cls,topic,msg):
 p=n.create_publisher(cls,topic,10);publishers.append((p,msg))
j=JointState();j.name=['LEFT_J1'];j.position=[.2];add(JointState,'/feedback/joint',j)
b=io.BytesIO();Image.new('RGB',(64,32)).save(b,format='JPEG');im=CompressedImage();im.format='jpeg';im.data=b.getvalue();add(CompressedImage,'/camera/kfc_compressed',im)
c=String();c.data='test_calibration: true';add(String,'/camera/kfc_calib_data',c)
f=EEFeedback();f.ee_name='Linker_L6';f.status=0;v=EEJointState();v.name='IF_MCP_PITCH';v.position=50.;f.joint_states=[v];add(EEFeedback,'/feedback/ee/left',f)
a=EEJointControl();a.mode=0;a.joint_names=['IF_MCP_PITCH'];a.values=[50.];add(EEJointControl,'/linkerhand/w1/ee/left/command',a)
def tick():
 for p,m in publishers:
  if hasattr(m,'header'):m.header.stamp=n.get_clock().now().to_msg()
  p.publish(m)
n.create_timer(.1,tick)
try:rclpy.spin(n)
except BaseException:pass
finally:n.destroy_node()
'''
pub=subprocess.Popen([sys.executable,'-c',publisher_code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def call(command,task=None):
 args=['bash',str(code/'record.sh'),command]
 if task:args.append(task)
 p=subprocess.run(args,text=True,capture_output=True,timeout=100)
 try:r=json.loads(p.stdout)
 except Exception:raise RuntimeError((args,p.returncode,p.stdout,p.stderr[-1000:]))
 print('CLI',command,p.returncode,r.get('result',{}).get('save_status'),flush=True)
 return p.returncode,r

def pid():return json.loads((runtime/'mcap_recorder.pid').read_text())['identity']['pid']
def active():return json.loads((runtime/'mcap_recorder_state.json').read_text())['active']
def wait_until(f,secs=12):
 end=time.monotonic()+secs
 while time.monotonic()<end:
  if f():return
  time.sleep(.2)
 raise RuntimeError('Timeout waiting for lifecycle result')
try:
 time.sleep(1)
 rc,r=call('start','native');assert rc==0,r;ep=pathlib.Path(r['result']['episode_dir']);time.sleep(2)
 rc,r=call('stop');assert rc==0 and r['result']['save_status']=='saved',r
 info=json.loads((ep/'recording_info.json').read_text());assert info['coverage_status']=='partial'
 assert info['topics_summary'].get('/camera/kfc_compressed',0)>0
 assert info['topics_summary'].get('/linkerhand/w1/ee/left/command',0)>0
 assert not any('motor_cmd' in t or 'eye_resize' in t or '/camera_l/' in t for t in info['expected_topics'])
 from mcap.reader import make_reader
 from rosidl_runtime_py.utilities import get_message
 from rclpy.serialization import deserialize_message
 count=0
 for fn in (ep/'raw').glob('*.mcap'):
  with fn.open('rb') as f:
   for schema,channel,message in make_reader(f).iter_messages():
    deserialize_message(message.data,get_message(schema.name));count+=1
 assert count==info['total_messages'];results.append({'case':'native_schema_and_partial_coverage','messages':count,'passed':True})
 rc,r=call('stop');assert rc!=0 and not r['success'];results.append({'case':'service_failure_shell_exit','passed':True})
 rc,r=call('start','sigterm');assert rc==0;ep=pathlib.Path(r['result']['episode_dir']);time.sleep(1);os.kill(pid(),signal.SIGTERM)
 wait_until(lambda:(ep/'recording_info.json').exists());info=json.loads((ep/'recording_info.json').read_text());assert info['save_status']=='saved',info
 results.append({'case':'resident_SIGTERM_finalizes','passed':True});time.sleep(.5)
 rc,r=call('start','parentkill');assert rc==0;ep=pathlib.Path(r['result']['episode_dir']);time.sleep(1);os.kill(pid(),signal.SIGKILL)
 wait_until(lambda:(ep/'worker_result.json').exists());wr=json.loads((ep/'worker_result.json').read_text());assert wr['reason']=='parent_lost',wr
 time.sleep(.3);rc,r=call('status');wait_until(lambda:(ep/'recording_info.json').exists());info=json.loads((ep/'recording_info.json').read_text());assert info['save_status']=='failed';results.append({'case':'resident_SIGKILL_child_shutdown_and_recovery','passed':True})
 rc,r=call('start','childexit');assert rc==0;ep=pathlib.Path(r['result']['episode_dir']);time.sleep(1)
 os.kill(json.loads((ep/'child_process.json').read_text())['pid'],signal.SIGTERM)
 wait_until(lambda:(ep/'recording_info.json').exists());info=json.loads((ep/'recording_info.json').read_text());assert info['save_status']=='failed';results.append({'case':'unexpected_bag_exit_fails','passed':True})
 pub.send_signal(signal.SIGINT);pub.wait(timeout=6);time.sleep(.5)
 rc,r=call('start','empty');assert rc==0;ep=pathlib.Path(r['result']['episode_dir']);time.sleep(1)
 rc,r=call('stop');assert rc==0 and r['result']['save_status']=='saved',r
 results.append({'case':'all_selected_streams_absent_allowed','count':r['result']['total_messages'],'passed':True})
 print(json.dumps(results,indent=2),flush=True)
finally:
 if pub.poll() is None:pub.send_signal(signal.SIGINT);pub.wait(timeout=6)
 try:os.kill(pid(),signal.SIGTERM)
 except (FileNotFoundError,ProcessLookupError):pass
 (root/'native_results.json').write_text(json.dumps(results,indent=2))
