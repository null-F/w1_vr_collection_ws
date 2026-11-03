"""LinkerZ 力源只选定一次，选定后不再更换。"""

from types import SimpleNamespace

from linkerbot_ffg_ros.sources.ros_linkerbot_force import (
    ForceSourceArbiter,
    default_force_topics,
    frame_is_fresh,
    resolve_force_topics_for_side,
)


def _meta(*, valid=True, stale=False):
    return SimpleNamespace(valid=valid, stale=stale)


def test_fresh_frame_needs_valid_and_not_stale():
    assert frame_is_fresh(SimpleNamespace(meta=_meta()))
    assert not frame_is_fresh(SimpleNamespace(meta=_meta(valid=False)))
    assert not frame_is_fresh(SimpleNamespace(meta=_meta(stale=True)))
    assert not frame_is_fresh(SimpleNamespace(meta=None))
    assert not frame_is_fresh(SimpleNamespace())


def test_default_topics_subscribe_all_three():
    topics = default_force_topics("/linkerbot_hand/command/angles")
    assert topics == [
        ("/linkerbot_hand/state/force_fns", "fns"),
        ("/linkerbot_hand/state/force_fn", "fn"),
        ("/linkerbot_hand/state/normal_force_resultant", "resultant"),
    ]
    assert resolve_force_topics_for_side(None, "/left/command/angles") == [
        ("/left/state/force_fns", "fns"),
        ("/left/state/force_fn", "fn"),
        ("/left/state/normal_force_resultant", "resultant"),
    ]


def test_override_uses_only_listed_topics():
    topics = resolve_force_topics_for_side(
        None,
        "/linkerbot_hand/command/angles",
        override=["/custom/state/force_fn", "/custom/other"],
    )
    assert topics == [("/custom/state/force_fn", "fn"), ("/custom/other", "custom")]


def test_fns_locks_immediately_and_stays():
    arbiter = ForceSourceArbiter(("fns", "fn", "resultant"))
    assert not arbiter.observe("fn", 0.0)
    assert arbiter.active is None
    assert arbiter.observe("fns", 0.2)
    assert arbiter.active == "fns"
    assert not arbiter.observe("fn", 5.0)
    assert arbiter.observe("fns", 5.0)
    assert arbiter.active == "fns"
    assert arbiter.poll(6.0) is None


def test_lower_source_locks_after_wait():
    arbiter = ForceSourceArbiter(("fns", "fn", "resultant"))
    assert not arbiter.observe("fn", 0.0)
    assert arbiter.poll(0.49) is None
    assert arbiter.poll(0.5) == "fn"
    assert arbiter.active == "fn"
    assert not arbiter.observe("fns", 1.0)
    assert not arbiter.observe("resultant", 1.0)
    assert arbiter.observe("fn", 1.0)


def test_resultant_waits_and_yields_to_fn_before_lock():
    arbiter = ForceSourceArbiter(("fns", "fn", "resultant"))
    assert not arbiter.observe("resultant", 0.0)
    assert not arbiter.observe("fn", 0.2)
    assert arbiter.observe("fn", 0.5)
    assert arbiter.active == "fn"
    assert not arbiter.observe("resultant", 2.0)


def test_resultant_locks_when_it_is_the_only_source():
    arbiter = ForceSourceArbiter(("fns", "fn", "resultant"))
    assert not arbiter.observe("resultant", 0.0)
    assert arbiter.observe("resultant", 0.5)
    assert arbiter.active == "resultant"


def test_pinned_source_locks_immediately():
    arbiter = ForceSourceArbiter(("resultant",))
    assert not arbiter.observe("fns", 0.0)
    assert arbiter.observe("resultant", 0.0)
    assert arbiter.active == "resultant"
