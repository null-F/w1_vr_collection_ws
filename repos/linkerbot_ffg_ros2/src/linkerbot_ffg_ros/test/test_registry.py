"""锁住型号登记、平滑器只保留一份，以及平滑参数写进配置。"""

import pytest

from linkerbot_ffg_ros.detect.robot import normalize_robot_name
from linkerbot_ffg_ros.hands import l6, o6
from linkerbot_ffg_ros.hands.smoothing import MotorSmoother
from linkerbot_ffg_ros.mappers.l6 import L6Mapper
from linkerbot_ffg_ros.mappers.l10 import L10Mapper
from linkerbot_ffg_ros.settings import resolve_settings
from linkerbot_ffg_ros.teleop.registry import get_mapper_class


def test_smoother_class_is_defined_once():
    assert o6.MotorSmoother is MotorSmoother
    assert "MotorSmoother" not in l6.__dict__


def test_reported_names_normalize_without_changing_aliases():
    assert normalize_robot_name("g20") == "l20"
    assert normalize_robot_name("l6p") == "l6"
    assert normalize_robot_name("l20-lite") == "l20lite"
    assert normalize_robot_name("l20lite") == "l20lite"
    assert get_mapper_class("l20lite") is L10Mapper
    assert get_mapper_class("l6") is L6Mapper
    assert L6Mapper.robot_name == "l6"


def test_no_smooth_is_stored_on_settings():
    settings = resolve_settings({}, cli_no_smooth=True)
    assert settings.smooth is False


def test_invalid_smooth_parameters_are_rejected():
    with pytest.raises(ValueError):
        resolve_settings({}, cli_smooth_alpha=0)
    with pytest.raises(ValueError):
        resolve_settings({}, cli_smooth_max_step=0)
