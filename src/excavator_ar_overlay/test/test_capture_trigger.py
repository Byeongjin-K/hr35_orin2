"""Trigger policy for the snapshot capture node.

Interval mode had no coverage at all: it was written for a field session that
has not happened yet, so every one of its decisions was unverified.
"""

from __future__ import annotations

from excavator_ar_overlay.capture_trigger import (
    FreshnessGate,
    IntervalTrigger,
    exposure_warning,
)


def test_first_tick_announces_and_does_not_fire():
    trigger = IntervalTrigger(12.0)
    result = trigger.tick(100.0)
    assert result.fire is False
    assert "every 12s" in result.announce


def test_fires_once_a_full_period_has_passed():
    trigger = IntervalTrigger(12.0)
    trigger.tick(100.0)
    assert trigger.tick(111.9).fire is False
    assert trigger.tick(112.0).fire is True


def test_period_restarts_after_a_shot():
    trigger = IntervalTrigger(10.0)
    trigger.tick(0.0)
    assert trigger.tick(10.0).fire is True
    assert trigger.tick(19.0).fire is False
    assert trigger.tick(20.0).fire is True


def test_countdown_announces_whole_seconds_only():
    trigger = IntervalTrigger(12.0)
    trigger.tick(0.0)
    announced = []
    now = 0.25
    while now < 12.0:
        result = trigger.tick(now)
        if result.announce:
            announced.append(result.announce.strip())
        now += 0.25
    assert announced == [f"{n}..." for n in range(11, 0, -1)]


def test_defer_retries_without_waiting_a_whole_period():
    trigger = IntervalTrigger(12.0)
    trigger.tick(0.0)
    assert trigger.tick(12.0).fire is True
    trigger.defer(12.0)
    assert trigger.tick(12.25).fire is True


def test_gate_accepts_the_first_capture():
    assert FreshnessGate().reject_reason(1, 1) is None


def test_gate_rejects_a_repeated_cloud():
    gate = FreshnessGate()
    gate.mark_saved(7, 3)
    reason = gate.reject_reason(7, 4)
    assert reason is not None
    assert "cloud" in reason and "image" not in reason


def test_gate_rejects_a_repeated_image():
    gate = FreshnessGate()
    gate.mark_saved(7, 3)
    reason = gate.reject_reason(8, 3)
    assert reason is not None
    assert "image" in reason and "cloud" not in reason


def test_gate_accepts_when_both_streams_advanced():
    gate = FreshnessGate()
    gate.mark_saved(7, 3)
    assert gate.reject_reason(8, 4) is None


def test_exposure_warning_flags_a_blown_out_frame():
    warning = exposure_warning(227.5)  # measured on a real capture, 2026-09-07
    assert warning is not None
    assert "bright" in warning


def test_exposure_warning_flags_a_black_frame():
    warning = exposure_warning(4.0)
    assert warning is not None
    assert "dark" in warning


def test_exposure_warning_is_silent_on_a_normal_frame():
    assert exposure_warning(136.3) is None
