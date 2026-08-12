"""Retention policy for the event-driven /ai_status/action topic.

`AiActionStatus` is published only on phase transitions. A dig step runs for
roughly 30 s, so for most of the time no new message arrives. Dropping the
overlay when nothing is received would leave the screen blank for almost the
whole cycle, so the last message is held until a phase says otherwise.

Kept free of the message type itself so the policy is testable without the
HR35 `excavator_msgs` overlay on the path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Phases that mean "there is no active plan to draw".
CLEARING_PHASES = frozenset({"idle", "terminated"})


@dataclass(frozen=True)
class DigAction:
    """The subset of AiActionStatus the overlay draws."""

    phase: str
    rows: np.ndarray
    cols: np.ndarray
    start_row: int
    start_col: int
    p_meter: float
    d_meter: float
    d_units: float
    length_meter: float
    swing_angle_excavator_deg: float
    mean_remaining_delta_units: float
    stamp_ns: int = 0

    @classmethod
    def from_message(cls, msg, stamp_ns: int = 0) -> "DigAction":
        return cls(
            phase=str(msg.phase),
            rows=np.asarray(list(msg.selected_rows), dtype=np.int32),
            cols=np.asarray(list(msg.selected_cols), dtype=np.int32),
            start_row=int(msg.start_row),
            start_col=int(msg.start_col),
            p_meter=float(msg.p_meter),
            d_meter=float(msg.d_meter),
            d_units=float(msg.d_units),
            length_meter=float(msg.length_meter),
            swing_angle_excavator_deg=float(msg.swing_angle_excavator_deg),
            mean_remaining_delta_units=float(msg.mean_remaining_delta_units),
            stamp_ns=int(stamp_ns),
        )

    def has_cells(self) -> bool:
        return self.rows.size > 0 and self.rows.size == self.cols.size

    def hud_lines(self) -> "list[str]":
        remaining = self.mean_remaining_delta_units
        verdict = "on target"
        if remaining > 0.1:
            verdict = f"dig {remaining * 0.1:+.2f} m"
        elif remaining < -0.1:
            verdict = f"over-dug {remaining * 0.1:+.2f} m"
        return [
            f"phase: {self.phase}",
            f"p={self.p_meter:.2f}m  len={self.length_meter:.2f}m  "
            f"d={self.d_meter:.2f}m",
            f"swing={self.swing_angle_excavator_deg:+.1f}deg  cells={self.rows.size}",
            f"remaining: {remaining:+.2f}u ({verdict})",
        ]


@dataclass
class ActionRetainer:
    """Holds the newest action, and forgets it when the phase says to."""

    current: "DigAction | None" = field(default=None)

    def update(self, action: DigAction) -> "DigAction | None":
        if action.phase in CLEARING_PHASES:
            self.current = None
        else:
            self.current = action
        return self.current

    def get(self) -> "DigAction | None":
        return self.current

    def status_line(self) -> str:
        if self.current is None:
            return "no active dig plan"
        return f"plan held: {self.current.phase}"
