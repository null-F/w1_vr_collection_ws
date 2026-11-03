"""锁住力曲线的死区和上限，不锁中间某一个精确小数。"""

import pytest

from linkerbot_ffg_ros.force.mass_to_force import mass_to_force
from linkerbot_ffg_ros.settings.loader import _resolve_force

_KW = {
    "max_force": 255,
    "trigger_mass": 200,
    "mass_max": 2000,
    "force_onset": 150,
}


def test_at_or_below_trigger_is_zero():
    assert mass_to_force(0, **_KW) == 0.0
    assert mass_to_force(200, **_KW) == 0.0


def test_just_above_trigger_is_positive_and_capped():
    value = mass_to_force(201, **_KW)
    assert 0.0 < value <= _KW["max_force"]


def test_negative_trigger_mass_rejected_at_config_load():
    with pytest.raises(ValueError, match="trigger_mass 不可为负"):
        _resolve_force(
            {"force_feedback": {"trigger_mass": -100}},
            "o6",
            cli_force=None,
            cli_force_max=None,
        )


def test_default_force_config_keeps_zero_touch_at_zero_force():
    spec = _resolve_force({}, "o6", cli_force=None, cli_force_max=None)
    assert spec.trigger_mass == 200
    assert mass_to_force(
        0.0,
        max_force=spec.max_force,
        trigger_mass=spec.trigger_mass,
        mass_max=spec.mass_max,
        force_onset=spec.force_onset,
    ) == 0.0
