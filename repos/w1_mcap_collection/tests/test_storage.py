import json
from pathlib import Path
import yaml
from mcap.writer import Writer
from storage import validate_bag, file_result, process_identity, identity_alive


def bag(tmp_path, count=1):
    p = tmp_path / 'raw'; p.mkdir()
    with (p/'raw_0.mcap').open('wb') as f:
        w = Writer(f); w.start(profile='ros2')
        s = w.register_schema(name='std_msgs/msg/String', encoding='ros2msg', data=b'string data\n')
        c = w.register_channel(topic='/test', message_encoding='cdr', schema_id=s)
        for i in range(count): w.add_message(c, 1000000000+i, b'\x00\x01\x00\x00\x01\x00\x00\x00\x00', 1000000000+i)
        w.finish()
    m={'rosbag2_bagfile_information':{'storage_identifier':'mcap','relative_file_paths':['raw_0.mcap'], 'message_count':count, 'duration':{'nanoseconds':count}, 'topics_with_message_count':[{'topic_metadata':{'name':'/test','type':'std_msgs/msg/String'},'message_count':count}]}}
    (p/'metadata.yaml').write_text(yaml.safe_dump(m))
    return p


def test_valid_partial_allowed(tmp_path):
    v=validate_bag(bag(tmp_path), ['/test','/missing'])
    assert v['valid'] and v['coverage_status']=='partial'
    assert v['missing_topics']==['/missing']
    assert file_result(v, {'reason':'signal', 'returncode':0, 'forced':False}, 'stop')['save_status']=='saved'


def test_missing_metadata_is_failure(tmp_path):
    v=validate_bag(tmp_path, ['/test'])
    assert not v['valid']
    assert file_result(v, {'reason':'signal','returncode':0,'forced':False}, 'stop')['save_status']=='failed'


def test_metadata_count_mismatch(tmp_path):
    p=bag(tmp_path);m=yaml.safe_load((p/'metadata.yaml').read_text());m['rosbag2_bagfile_information']['message_count']=99
    (p/'metadata.yaml').write_text(yaml.safe_dump(m))
    assert not validate_bag(p, ['/test'])['valid']


def test_truncated_file_fails(tmp_path):
    p=bag(tmp_path);f=p/'raw_0.mcap';f.write_bytes(f.read_bytes()[:-10])
    assert not validate_bag(p, ['/test'])['valid']


def test_unexpected_child_exit_not_saved(tmp_path):
    v=validate_bag(bag(tmp_path), ['/test'])
    assert file_result(v, {'reason':'child_exit','returncode':0,'forced':False}, 'unexpected_exit')['save_status']=='failed'
    assert file_result(v, {'reason':'signal','returncode':1,'forced':False}, 'stop')['save_status']=='failed'
    assert file_result(v, {'reason':'signal','returncode':0,'forced':True}, 'stop')['save_status']=='failed'


def test_identity_rejects_reused_pid():
    import os
    d=process_identity(os.getpid()); assert identity_alive(d)
    d['start_ticks'] += 1; assert not identity_alive(d)
