import json
from pathlib import Path
import time

from mcap.writer import Writer
import yaml

from audit_streams import audit
from device_snapshot import HeadCalibration


def calibration(serial):
    matrix = [[1,0,0],[0,1,0],[0,0,1]]
    return yaml.safe_dump(dict(SN=serial, cam1_k=matrix,cam2_k=matrix,R_l_r=matrix,
                               dist_1=[[0]*5],dist_2=[[0]*5],t_l_r=[[10],[0],[0]],image_size=[[640,480]]))


def test_episode_calibration_late_changed_stale_and_recovery(tmp_path):
    monitor = HeadCalibration()
    first = calibration('camera-one')
    monitor.observe('bad')
    path = tmp_path/'device_info.json'
    monitor.attach(path, dict(head_calibration_raw='obsolete cache'))
    def load():
        return json.loads(path.read_text())
    assert 'head_calibration_raw' not in load()
    for raw in (first,first, first+'\n', calibration('camera-two')):
        monitor.observe(raw)
    monitor.last_seen = time.monotonic() - 10
    monitor.tick()
    monitor.detach()
    result = load()
    assert result['head_calibration_raw'] == first
    assert len(result['head_calibration']['versions']) == 2
    assert [r['status'] for r in result['head_calibration']['history']] == ['invalid','available','available','missing']
    monitor.attach(tmp_path/'second.json',dict(head_calibration_raw=first))
    assert 'head_calibration_raw' not in json.loads((tmp_path/'second.json').read_text())


def test_profile_and_split_readback(tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root/'topics.yaml').read_text())
    topics = config['continuous']+config['command_or_event']+config['static']
    assert len(set(topics)) == len(topics) == 30
    assert '/camera/kfc_calib_data' not in topics and '/camera/kfc_status' in config['optional']
    qos = yaml.safe_load((root/'qos_overrides.yaml').read_text())
    sensors = [t for t in topics if t.startswith(('/orbbec/','/laser_scan/'))]
    assert len(sensors) == 10 and all(qos[t]['reliability']=='reliable' for t in sensors)
    raw = tmp_path/'raw'
    raw.mkdir()
    files = ['a.mcap','b.mcap']
    for file,ns in zip(files,[10,30]):
        with (raw/file).open('wb') as f:
            w=Writer(f)
            w.start(profile='ros2')
            schema=w.register_schema('sensor_msgs/msg/LaserScan','ros2msg',b'float32[] ranges')
            channel=w.register_channel('/laser_scan/rear','cdr',schema)
            w.add_message(channel,ns,b'example',ns)
            w.finish()
    (raw/'metadata.yaml').write_text(yaml.safe_dump(dict(rosbag2_bagfile_information=dict(relative_file_paths=files))))
    (tmp_path/'operator_events.jsonl').write_text('\n'.join(json.dumps(dict(wall_ns=ns,source=tag))
                                                      for ns,tag in [(1,'initial'),(25,'follow'),(40,'end')]))
    result=audit(tmp_path)
    assert result['topics']['/laser_scan/rear']['max_gap_ns']==20
    assert result['topics']['/orbbec/front/depth']['count']==0
    windows=result['operator_windows']
    assert [w['topics']['/laser_scan/rear']['count'] for w in windows]==[1,1]
    assert windows[0]['topics']['/laser_scan/rear']['max_gap_including_edges_ns']==15
