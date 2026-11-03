"""锁住 LinkerZ 重排：O6 四舍五入，L20 固定下标，O30 只交换前两路。"""

from linkerbot_ffg_ros.sinks.remap import remap_for_linker_z

_L20_ORDER = (10, 5, 0, 15, 6, 1, 16, 7, 2, 17, 8, 3, 18, 9, 4, 19)


def test_o6_passthrough_rounds():
    assert remap_for_linker_z("o6", [10.4, 10.6, 0, 255, 3, 4]) == [
        10.0, 11.0, 0.0, 255.0, 3.0, 4.0,
    ]


def test_l20_reorder_is_fixed():
    positions = list(range(20))
    assert remap_for_linker_z("l20", positions) == [float(positions[i]) for i in _L20_ORDER]


def test_o30_swaps_first_two_only_when_asked():
    positions = list(range(20))
    plain = remap_for_linker_z("o30", positions, o30_swap_01=False)
    swapped = remap_for_linker_z("o30", positions, o30_swap_01=True)
    assert plain == [float(i) for i in positions]
    assert swapped[0] == 1.0
    assert swapped[1] == 0.0
    assert swapped[2:] == plain[2:]
