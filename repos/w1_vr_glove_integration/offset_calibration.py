"""Two-placement controller mounting calibration; no robot control interfaces."""
import math
import time

import numpy as np
from scipy.spatial.transform import Rotation

import operator_state as signals


def summarize(frames):
    if len(frames) < 25:
        raise ValueError('有效独立样本不足 25 帧，请保持手柄追踪')
    p = np.array([[f['position'][k] for k in 'xyz'] for f in frames], dtype=float)
    q = np.array([[f['quaternion'][k] for k in 'xyzw'] for f in frames], dtype=float)
    if not np.isfinite(p).all() or not np.isfinite(q).all() or np.any(abs(np.linalg.norm(q, axis=1)-1) > .02):
        raise ValueError('追踪数据无效')
    rotation = Rotation.from_quat(q).mean()
    center = p.mean(axis=0)
    spread = float(np.max(np.linalg.norm(p-center, axis=1))*1000)
    angle = float(np.max((rotation.inv()*Rotation.from_quat(q)).magnitude())*180/np.pi)
    if spread > 8 or angle > 3:
        raise ValueError(f'采样不稳定：最大位置偏差 {spread:.1f} mm、角度偏差 {angle:.1f}°，请固定手腕重采')
    return dict(position_m=center.tolist(), quaternion_xyzw=rotation.as_quat().tolist(),
                frames=len(frames), max_position_deviation_mm=spread, max_angle_deviation_deg=angle)


def sample(path, side, expected_stream=None, duration=2.0):
    rows, stamps = [], set()
    start, stream = time.monotonic(), expected_stream
    while time.monotonic()-start < duration:
        if signals.fresh('vr.json').get('press') or signals.fresh('pedal.json').get('press'):
            raise ValueError('请先关闭跟随踏板控制，再进行标定')
        data = signals.read(path)
        stamp = data.get('monotonic')
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or not 0 <= time.monotonic()-stamp < .25:
            raise ValueError('实时追踪中断，请戴好头显并进入遥操页面')
        source = data.get('stream_id')
        if not isinstance(source, str) or not source:
            raise ValueError('缺少追踪会话标识，请重新加载 VR 服务')
        if stream is None:
            stream = source
        if source != stream:
            raise ValueError('VR 连接会话已变化，请从掌心参考重新采集')
        pose = data.get('poses', {}).get(side+'_controller')
        if not isinstance(pose, dict):
            raise ValueError('所选手柄没有有效追踪')
        try:
            xyz = np.array([pose['position'][k] for k in 'xyz'], dtype=float)
            head = data['poses']['head']
            head_xyz = np.array([head['position'][k] for k in 'xyz'], dtype=float)
            distance = float(np.linalg.norm(xyz-head_xyz))
            if not math.isfinite(distance) or not .10 <= distance <= 1.2:
                raise ValueError('手柄距头显过近或位姿无效，请将手柄放在头显前方并确认追踪')
            other = data['poses'].get(('left' if side == 'right' else 'right')+'_controller')
            if other:
                other_xyz = np.array([other['position'][k] for k in 'xyz'], dtype=float)
                if np.linalg.norm(xyz-other_xyz) < .001:
                    raise ValueError('左右手柄位置重合，疑似默认占位数据，请确认真实手柄追踪')
        except (KeyError, TypeError) as exc:
            raise ValueError('缺少有效头显或手柄位姿') from exc
        if stamp not in stamps:
            stamps.add(stamp)
            rows.append(pose)
        time.sleep(.025)
    try:
        stats = summarize(rows)
    except (KeyError, TypeError) as exc:
        raise ValueError('手柄位姿格式无效') from exc
    return dict(stream_id=stream, captured_monotonic=time.monotonic(), frames=rows, summary=stats)


def solve(palm, back):
    if palm['stream_id'] != back['stream_id']:
        raise ValueError('两组追踪会话不一致，请重新采集')
    if not 0 <= back['captured_monotonic']-palm['captured_monotonic'] <= 600:
        raise ValueError('掌心参考超过 10 分钟，请重新采集')
    a, b = palm['summary'], back['summary']
    rp, rb = Rotation.from_quat(a['quaternion_xyzw']), Rotation.from_quat(b['quaternion_xyzw'])
    translation = rb.inv().apply(np.array(a['position_m'])-b['position_m'])
    rotation = rb.inv()*rp
    if not np.isfinite(translation).all() or np.linalg.norm(translation) > .5:
        raise ValueError('求得的安装偏移超过 50 cm，可能移动了手腕，请重新采集')
    matrix = np.eye(4)
    matrix[:3, :3], matrix[:3, 3] = rotation.as_matrix(), translation
    return dict(offset=dict(translation_m=translation.tolist(), rotation_xyz_deg=rotation.as_euler('xyz', degrees=True).tolist()),
                matrix=matrix.tolist(), translation_length_cm=float(np.linalg.norm(translation)*100),
                rotation_angle_deg=float(rotation.magnitude()*180/np.pi),
                note='已自动求解，仅用于预览。两次手腕不动的条件无法仅靠手柄自动验证；请在多个姿态下检查。')
