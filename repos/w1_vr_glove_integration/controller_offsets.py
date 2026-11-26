"""Convert hand-back controller poses to the original grip reference before IK."""
from dataclasses import replace
import json
import math

from scipy.spatial.transform import Rotation

from operator_state import ROOT

CONFIG = ROOT / 'config/w1/controller_offsets.json'


def vector(value, name):
    if (not isinstance(value, list) or len(value) != 3
            or not all(type(v) in (int, float) and math.isfinite(v) for v in value)):
        raise ValueError(f'{name} must contain three finite numbers')
    return value


class ControllerOffsets:
    def __init__(self, path=CONFIG):
        try:
            config = json.loads(path.read_text())
        except FileNotFoundError:
            config = {'enabled': False}
        if type(config.get('enabled')) is not bool:
            raise ValueError('Controller offsets require a boolean enabled field')
        self.enabled = config['enabled']
        self.transforms = {}
        if self.enabled:
            for side in ('left', 'right'):
                data = config[side]
                translation = vector(data['translation_m'], side + '.translation_m')
                angles = vector(data['rotation_xyz_deg'], side + '.rotation_xyz_deg')
                self.transforms[side] = (translation, Rotation.from_euler('xyz', angles, degrees=True))
        self.config = config
        print('LINKERHAND_CONTROLLER_OFFSETS ' + json.dumps(config), flush=True)

    def apply(self, message):
        if not self.enabled:
            return message
        poses = {}
        for side, (translation, offset_rotation) in self.transforms.items():
            pose = getattr(message, side + '_controller')
            rotation = Rotation.from_quat([pose['quaternion'][k] for k in 'xyzw'])
            # T_corrected = T_controller @ T_offset. Translation rotates with the controller.
            position = [pose['position'][k] for k in 'xyz']
            corrected_position = position + rotation.apply(translation)
            corrected_rotation = (rotation * offset_rotation).as_quat()
            poses[side + '_controller'] = dict(
                pose, position=dict(zip('xyz', corrected_position.tolist())),
                quaternion=dict(zip('xyzw', corrected_rotation.tolist())))
        return replace(message, **poses)
