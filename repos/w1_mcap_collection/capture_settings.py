"""Topic selection and auditable controller installation metadata, without ROS I/O."""
import hashlib
import json
import math
from pathlib import Path

GROUPS = ('continuous', 'command_or_event', 'static', 'optional')


def select_topics(config, auxiliary=False):
    for group in GROUPS+('disabled','metadata_only'):
        items=config.get(group, [])
        if not isinstance(items,list) or any(not isinstance(t,str) or not t.startswith('/') for t in items):
            raise ValueError('Invalid topic list: '+group)
        if len(items)!=len(set(items)):
            raise ValueError('Duplicate topic in '+group)
    metadata=config.get('metadata_only',[])
    if any(not t.endswith('/camera_info') for t in metadata):
        raise ValueError('metadata_only currently supports sensor_msgs/CameraInfo topics only')
    excluded=set(config.get('disabled',[]))|set(metadata)
    groups=GROUPS if auxiliary else GROUPS[:3]
    topics=[]
    for group in groups:
        for topic in config.get(group,[]):
            if topic not in excluded and topic not in topics:topics.append(topic)
    if not topics:raise ValueError('No MCAP topics selected')
    return topics,[t for t in metadata if t not in config.get('disabled',[])]


def offset_config(data):
    if not isinstance(data,dict) or type(data.get('enabled')) is not bool:
        raise ValueError('Invalid controller offset enabled flag')
    result={'enabled':data['enabled']}
    for side in ('left','right'):
        value=data.get(side,{})
        result[side]={}
        for field in ('translation_m','rotation_xyz_deg'):
            vector=value.get(field)
            if (not isinstance(vector,list) or len(vector)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in vector)):
                raise ValueError('Invalid controller offset '+side+'.'+field)
            result[side][field]=list(vector)
    return result


def mounting_snapshot(config_path, active_path):
    warnings=[]
    result={'schema_version':1,'transform_convention':'T_virtual_grip = T_controller @ T_offset',
            'translation_unit':'m','rotation_convention':'extrinsic_xyz_degrees',
            'config_path':str(config_path),'runtime_verified':False}
    try:
        raw=Path(config_path).read_bytes();result['configured']=offset_config(json.loads(raw))
        result['config_file_sha256']=hashlib.sha256(raw).hexdigest()
    except (OSError,ValueError,TypeError) as exc:
        result['configured']=None;warnings.append('Controller mounting config unavailable: '+str(exc))
    try:
        active=json.loads(Path(active_path).read_text())
        pid=active['pid'];fields=(Path('/proc')/str(int(pid))/'stat').read_text().rsplit(')',1)[1].split()
        if (fields[0]=='Z' or fields[19]!=active['pid_start'] or
                Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=active['boot_id']):
            raise ValueError('stale VR process identity')
        result['effective']=offset_config(active['config'])
        result['runtime_verified']=True
        result['runtime_owner']={k:active[k] for k in ('pid','pid_start','boot_id')}
        result['config_matches_runtime']=result['configured']==result['effective']
        if not result['config_matches_runtime']:warnings.append('Controller config differs from running VR; effective records the loaded VR value')
    except (OSError,ValueError,TypeError,KeyError,IndexError) as exc:
        result['effective']=None;result['config_matches_runtime']=None
        warnings.append('Controller runtime offsets not verified: '+str(exc))
    return result,warnings


def camera_parameters(msg):
    params=dict(frame_id=msg.header.frame_id,height=int(msg.height),width=int(msg.width),
                distortion_model=msg.distortion_model,d=list(msg.d),k=list(msg.k),r=list(msg.r),p=list(msg.p),
                binning_x=int(msg.binning_x),binning_y=int(msg.binning_y),
                roi={key:getattr(msg.roi,key) for key in ('x_offset','y_offset','height','width','do_rectify')})
    if params['width']<=0 or params['height']<=0 or len(params['k'])!=9 or len(params['r'])!=9 or len(params['p'])!=12:
        raise ValueError('Invalid CameraInfo dimensions/matrices')
    if not all(math.isfinite(v) for key in ('d','k','r','p') for v in params[key]) or params['k'][0]<=0 or params['k'][4]<=0:
        raise ValueError('Invalid CameraInfo calibration values')
    return params
