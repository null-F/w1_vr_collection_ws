"""Immutable named offset groups and explicit, per-hand rotation-aware averaging."""
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import time

import numpy as np
from scipy.spatial.transform import Rotation


def clean_offset(value):
    if not isinstance(value, dict):
        raise ValueError('映射参数格式无效')
    result = {}
    for field, bound in (('translation_m', .5), ('rotation_xyz_deg', 180)):
        vector = value.get(field)
        if (not isinstance(vector, list) or len(vector) != 3 or
                any(type(v) not in (int, float) or not np.isfinite(v) or abs(v) > bound for v in vector)):
            raise ValueError('映射参数超出范围或不是有限数值')
        result[field] = list(vector)
    return result


def clean_config(value):
    if not isinstance(value, dict) or type(value.get('enabled')) is not bool:
        raise ValueError('完整映射配置无效')
    return dict(enabled=value['enabled'], **{s: clean_offset(value.get(s)) for s in ('left', 'right')})


class ProfileStore:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()

    def listing(self):
        with self.lock:
            records, warnings = [], []
            if self.root.exists():
                for path in sorted(self.root.glob('*.json'), key=lambda p: (p.stat().st_mtime_ns, p.name)):
                    try:
                        records.append(self.get(path.stem))
                    except (ValueError, OSError, KeyError, TypeError):
                        warnings.append('无法读取映射组：'+path.name)
            records.sort(key=lambda r: r.get("source") != "initial_config")
            return records, warnings

    def get(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{32}', key):
            raise ValueError('映射组编号无效')
        path = self.root / (key+'.json')
        try:
            record = json.loads(path.read_text())
        except OSError as exc:
            raise ValueError('映射组不存在') from exc
        if not isinstance(record, dict) or record.get('id') != key or record.get('schema_version') != 1:
            raise ValueError('映射组格式无效')
        if record.get('kind') == 'configuration':
            clean_config(record.get('config'))
        elif record.get('kind') in ('capture', 'average') and record.get('side') in ('left', 'right'):
            clean_offset(record.get('offset'))
        else:
            raise ValueError('映射组类型无效')
        return record

    def save(self, name, kind, **fields):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise ValueError('组名需要 1～80 个字符')
        if kind == 'configuration':
            fields['config'] = clean_config(fields.get('config'))
        elif kind in ('capture', 'average') and fields.get('side') in ('left', 'right'):
            fields['offset'] = clean_offset(fields.get('offset'))
        else:
            raise ValueError('映射组类型无效')
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            key = secrets.token_hex(16)
            record = dict(schema_version=1, id=key, name=name.strip(), kind=kind,
                          saved_wall_ns=time.time_ns(), **fields)
            path = self.root/(key+'.json')
            temporary = path.with_suffix('.tmp')
            try:
                temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            return record

    def seed(self, config):
        with self.lock:
            records, _ = self.listing()
            for record in records:
                if record.get('source') == 'initial_config':
                    return record
            valid = clean_config(config)
            digest = hashlib.sha256(json.dumps(valid, sort_keys=True).encode()).hexdigest()
            return self.save('当前保留组（升级前配置）', 'configuration', config=valid,
                             source='initial_config', config_sha256=digest)

    @staticmethod
    def for_side(record, side):
        if side not in ('left', 'right'):
            raise ValueError('请选择左手或右手')
        if record['kind'] == 'configuration':
            return clean_offset(record['config'][side])
        if record.get('side') != side:
            raise ValueError('不能混合左右手的映射')
        return clean_offset(record['offset'])

    def average(self, keys, side):
        if (not isinstance(keys, list) or not 2 <= len(keys) <= 30 or
                any(not isinstance(k, str) for k in keys) or len(set(keys)) != len(keys)):
            raise ValueError('请选择 2～30 个不同映射组')
        records = [self.get(key) for key in keys]
        if any(r['kind'] == 'average' for r in records):
            raise ValueError('请选择原始映射组，不要将平均组重复参与平均')
        offsets = [self.for_side(r, side) for r in records]
        translations = np.array([o['translation_m'] for o in offsets])
        rotations = Rotation.from_euler('xyz', [o['rotation_xyz_deg'] for o in offsets], degrees=True)
        center, mean_rotation = translations.mean(axis=0), rotations.mean()
        td = np.linalg.norm(translations-center, axis=1)*1000
        rd = (mean_rotation.inv()*rotations).magnitude()*180/np.pi
        max_t, max_r = float(td.max()), float(rd.max())
        review = max_t > 20 or max_r > 10
        return dict(side=side, offset=dict(translation_m=center.tolist(),
                    rotation_xyz_deg=mean_rotation.as_euler('xyz', degrees=True).tolist()),
                    source_ids=keys, count=len(keys), max_translation_deviation_mm=max_t,
                    max_rotation_deviation_deg=max_r, requires_review=review,
                    deviations=[dict(id=r['id'], name=r['name'], translation_mm=float(t), rotation_deg=float(a))
                                for r,t,a in zip(records,td,rd)],
                    note='组间差异较大，请检查安装和异常组，再决定采用结果。' if review else '已计算平均映射，仅供预览，尚未应用或保存。')
