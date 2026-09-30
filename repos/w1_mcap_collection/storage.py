"""File validation and Linux process identity helpers. No ROS or control APIs."""
from __future__ import annotations
import json
import os
from pathlib import Path
from collections import Counter
import yaml
from mcap.reader import make_reader


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2); f.write('\n')
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path, default=None):
    try: return json.loads(Path(path).read_text())
    except FileNotFoundError: return default


def process_identity(pid):
    try:
        p = Path('/proc') / str(int(pid))
        fields = (p/'stat').read_text().rsplit(')', 1)[1].split()
        return {'pid':int(pid), 'start_ticks':int(fields[19]), 'pgid':int(fields[2]),
                'state':fields[0], 'uid':p.stat().st_uid,
                'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (OSError, ValueError, IndexError): return None


def identity_alive(identity):
    if not identity: return False
    now = process_identity(identity.get('pid', -1))
    return bool(now and now['state'] != 'Z' and all(now[k] == identity.get(k)
                for k in ('pid','start_ticks','boot_id','uid')))


def signal_identity(identity, sig, group=False):
    if not identity_alive(identity): return False
    if identity['uid'] != os.getuid(): raise RuntimeError('Refusing different process owner')
    if group and identity['pgid'] != identity['pid']: raise RuntimeError('Not a dedicated process group')
    try:
        (os.killpg if group else os.kill)(identity['pid'], sig)
        return True
    except ProcessLookupError: return False


def validate_bag(bag_dir, expected_topics):
    """Validate footer/index/schema, boundary chunks and metadata counts; not a full payload scan."""
    bag_dir = Path(bag_dir).resolve()
    result = {'valid':False, 'errors':[], 'validation_scope':'summary_schema_counts_and_first_last_message',
              'topics_summary':{}, 'missing_topics':list(expected_topics), 'coverage_status':'partial',
              'total_messages':0, 'duration_sec':None, 'files':[], 'topics_config':[]}
    try:
        meta = yaml.safe_load((bag_dir/'metadata.yaml').read_text())
        b = meta['rosbag2_bagfile_information']
        if b['storage_identifier'] != 'mcap': raise ValueError('Storage is not mcap')
        files = b.get('relative_file_paths', [])
        if not files: raise ValueError('No MCAP files listed in metadata')
        counts = Counter(); total = 0
        for name in files:
            p = (bag_dir/name).resolve()
            if not p.is_relative_to(bag_dir) or p.suffix != '.mcap': raise ValueError('Invalid MCAP relative path')
            with p.open('rb') as f:
                f.seek(-8, 2)
                if f.read(8) != b'\x89MCAP0\r\n': raise ValueError(f'Missing MCAP footer: {name}')
                f.seek(0); reader = make_reader(f, validate_crcs=True)
                if reader.get_header().profile != 'ros2': raise ValueError('MCAP profile is not ros2')
                summary = reader.get_summary()
                if summary is None or summary.statistics is None: raise ValueError('MCAP summary/statistics missing')
                stat = summary.statistics
                channel_total = 0
                for cid, count in stat.channel_message_counts.items():
                    channel = summary.channels[cid]
                    schema = summary.schemas.get(channel.schema_id)
                    if count and (not schema or not schema.data or schema.encoding not in ('ros2msg','ros2idl')):
                        raise ValueError(f'Missing ROS schema for {channel.topic}')
                    if channel.message_encoding != 'cdr': raise ValueError('Non-CDR ROS message encoding')
                    counts[channel.topic] += count; channel_total += count
                if channel_total != stat.message_count: raise ValueError('Channel/message totals differ')
                if stat.message_count:
                    if next(reader.iter_messages(), None) is None: raise ValueError('First message unreadable')
                    if next(reader.iter_messages(reverse=True), None) is None: raise ValueError('Last message unreadable')
                total += stat.message_count
                result['files'].append({'path':name, 'bytes':p.stat().st_size, 'messages':stat.message_count})
        metadata_counts = {x['topic_metadata']['name']:int(x['message_count']) for x in b.get('topics_with_message_count', [])}
        if total != int(b['message_count']): raise ValueError('Metadata total differs from MCAP')
        if any(counts.get(t,0) != metadata_counts.get(t,0) for t in set(counts)|set(metadata_counts)):
            raise ValueError('Metadata per-topic counts differ from MCAP')
        result.update(valid=True, total_messages=total, topics_summary=dict(counts),
                      duration_sec=b.get('duration',{}).get('nanoseconds',0)/1e9,
                      topics_config=[x['topic_metadata'] for x in b.get('topics_with_message_count',[])])
        result['missing_topics'] = [t for t in expected_topics if counts.get(t,0)==0]
        result['coverage_status'] = 'complete' if not result['missing_topics'] else 'partial'
    except Exception as exc:
        result['errors'].append(f'{type(exc).__name__}: {exc}')
    return result


def file_result(validation, worker, reason):
    errors = list(validation['errors'])
    if not worker: errors.append('Recorder worker result missing')
    else:
        # ros2 CLI normally exits 0 on SIGINT; SIGINT/130 is allowed only after a requested stop
        # and a valid closed MCAP. Forced TERM/KILL or spontaneous exit always fails.
        if worker.get('returncode') not in (0, -2, 130): errors.append(f"Bag exit code: {worker.get('returncode')}")
        if worker.get('forced'): errors.append('Bag required forced termination')
        if worker.get('reason') != 'signal': errors.append(f"Worker ended: {worker.get('reason')}")
    if reason not in ('stop','shutdown','cancel'): errors.append(f'Recording interrupted: {reason}')
    return {**validation, 'save_status':'saved' if validation['valid'] and not errors else 'failed',
            'errors':errors, 'stop_reason':reason, 'worker':worker}
