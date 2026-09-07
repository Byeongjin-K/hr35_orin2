"""Trigger policy for the calibration snapshot node, kept free of rclpy.

The node itself only owns subscriptions and file writing; when to fire and
whether a capture is worth keeping are decisions with no ROS dependency, so
they live here where they can be tested without a graph.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TriggerResult:
    """What the caller should do with this tick."""

    fire: bool
    announce: "str | None" = None


class IntervalTrigger:
    """Fire every `period_s` seconds, announcing a countdown in between.

    Time based rather than machine based because nothing on the machine can
    place a 3D point off the boom's sagittal plane: boom, arm and bucket all
    move within it, and swinging turns the camera with them. A target that
    moves independently of the machine is the only source of lateral spread,
    and its motion cannot be observed from the machine's own state.
    """

    def __init__(self, period_s: float) -> None:
        self._period = float(period_s)
        self._since: "float | None" = None

    def tick(self, now: float) -> TriggerResult:
        if self._since is None:
            self._since = now
            return TriggerResult(
                False,
                f"interval mode: a shot every {self._period:.0f}s. "
                f"Move the target between shots, then stand clear.",
            )
        remaining = self._period - (now - self._since)
        if remaining > 0:
            if abs(remaining - round(remaining)) < 0.13 and remaining >= 1:
                return TriggerResult(False, f"  {int(round(remaining))}...")
            return TriggerResult(False)
        self._since = now
        return TriggerResult(True)

    def defer(self, now: float) -> None:
        """Re-arm for a short retry after a shot the node could not save."""
        self._since = now - self._period


class FreshnessGate:
    """Reject a capture whose cloud or image is the one already written.

    A dead stream is silent, not loud: the node keeps the last message it
    received, so a capture taken after the LiDAR or the camera stops produces a
    byte-identical duplicate of the previous pose and looks like a successful
    session. Every saved bundle must therefore carry frames neither of which
    has been saved before.
    """

    def __init__(self) -> None:
        self._saved: "tuple[int, int] | None" = None

    def reject_reason(self, cloud_seq: int, image_seq: int) -> "str | None":
        if self._saved is None:
            return None
        stale = []
        if cloud_seq == self._saved[0]:
            stale.append("cloud")
        if image_seq == self._saved[1]:
            stale.append("image")
        if not stale:
            return None
        return (
            f"no new {' and '.join(stale)} since the last capture "
            f"(stream stalled?); skipping this shot"
        )

    def mark_saved(self, cloud_seq: int, image_seq: int) -> None:
        self._saved = (cloud_seq, image_seq)


def exposure_warning(mean_level: float) -> "str | None":
    """Flag a frame whose exposure makes correspondence picking impossible.

    A blown-out or black frame still saves, still has the right size and still
    looks like a successful shot in the log; it is only useless later, when
    nobody is standing next to the machine any more.

    The thresholds are set where detail actually disappears rather than where a
    histogram looks unusual: a 227/255 frame measured live on 2026-09-07 had the
    sky and the fence washed into one white area.
    """
    if mean_level > 220.0:
        return (
            f"frame is too bright (mean {mean_level:.0f}/255) - detail is "
            f"washed out and correspondences cannot be picked from it; "
            f"reshoot with the camera away from the sun"
        )
    if mean_level < 30.0:
        return (
            f"frame is too dark (mean {mean_level:.0f}/255) - nothing in it "
            f"can be identified later; reshoot"
        )
    return None
