"""Tests for the /ai_status/action retention policy.

Uses a duck-typed stand-in rather than the real AiActionStatus so the policy is
testable without the HR35 excavator_msgs overlay on the path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from excavator_ar_overlay.ai_action import CLEARING_PHASES, ActionRetainer, DigAction


def fake_msg(phase="dig", rows=(10, 11), cols=(33, 34), **overrides):
    base = dict(
        phase=phase,
        selected_rows=list(rows),
        selected_cols=list(cols),
        start_row=10,
        start_col=33,
        p_meter=3.0,
        d_meter=0.2,
        d_units=2.0,
        length_meter=0.75,
        swing_angle_excavator_deg=-5.0,
        mean_remaining_delta_units=1.5,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_from_message_copies_every_drawn_field():
    action = DigAction.from_message(fake_msg())
    assert action.phase == "dig"
    assert list(action.rows) == [10, 11]
    assert list(action.cols) == [33, 34]
    assert action.start_row == 10 and action.start_col == 33
    assert action.p_meter == pytest.approx(3.0)
    assert action.has_cells()


def test_empty_selection_reports_no_cells():
    assert not DigAction.from_message(fake_msg(rows=(), cols=())).has_cells()


def test_mismatched_selection_lengths_report_no_cells():
    assert not DigAction.from_message(fake_msg(rows=(1, 2, 3), cols=(1,))).has_cells()


@pytest.mark.parametrize(
    "phase",
    ["inferring", "dig", "dig_done", "dig_failed", "dump", "reset", "reset_done"],
)
def test_non_clearing_phases_are_retained(phase):
    retainer = ActionRetainer()
    retainer.update(DigAction.from_message(fake_msg(phase=phase)))
    assert retainer.get() is not None
    assert retainer.get().phase == phase


@pytest.mark.parametrize("phase", sorted(CLEARING_PHASES))
def test_idle_and_terminated_clear_the_overlay(phase):
    retainer = ActionRetainer()
    retainer.update(DigAction.from_message(fake_msg(phase="dig")))
    assert retainer.get() is not None

    retainer.update(DigAction.from_message(fake_msg(phase=phase)))
    assert retainer.get() is None


def test_plan_survives_a_long_silence():
    """A dig step is ~30 s with no republish; the plan must not evaporate."""
    retainer = ActionRetainer()
    retainer.update(DigAction.from_message(fake_msg(phase="dig")))
    for _ in range(200):  # 100 s of 2 Hz render ticks, no new message
        assert retainer.get() is not None


def test_hud_reports_dig_more_and_over_dug_distinctly():
    dig_more = DigAction.from_message(
        fake_msg(mean_remaining_delta_units=1.5)
    ).hud_lines()
    over_dug = DigAction.from_message(
        fake_msg(mean_remaining_delta_units=-1.5)
    ).hud_lines()
    on_target = DigAction.from_message(
        fake_msg(mean_remaining_delta_units=0.0)
    ).hud_lines()

    assert any("dig +0.15 m" in line for line in dig_more)
    assert any("over-dug -0.15 m" in line for line in over_dug)
    assert any("on target" in line for line in on_target)


def test_hud_covers_every_field_the_spec_requires():
    lines = " ".join(DigAction.from_message(fake_msg()).hud_lines())
    for token in ("phase", "p=", "len=", "d=", "swing=", "remaining"):
        assert token in lines


def test_status_line_reflects_retention():
    retainer = ActionRetainer()
    assert retainer.status_line() == "no active dig plan"
    retainer.update(DigAction.from_message(fake_msg(phase="dig")))
    assert "dig" in retainer.status_line()
