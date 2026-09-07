"""Guards on the correspondence solver script.

The script is the only path from a field session to a calibrated extrinsic, and
its inputs are hand-typed pixel coordinates, so the input check matters as much
as the solve.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "solve_extrinsic_pnp.py"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("solve_extrinsic_pnp", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pair(u, v):
    return {"px": [u, v], "xyz": [1.0, 2.0, 3.0], "note": "p"}


def test_in_frame_pixels_pass(tool):
    pairs = [pair(10, 10), pair(1279, 799), pair(640, 400)]
    assert tool.pixel_bounds_error(pairs, 1280, 800) is None


def test_a_pixel_past_the_right_edge_is_rejected(tool):
    error = tool.pixel_bounds_error([pair(10, 10), pair(1400, 400)], 1280, 800)
    assert error is not None
    assert "1400" in error


def test_a_negative_pixel_is_rejected(tool):
    error = tool.pixel_bounds_error([pair(-5, 400)], 1280, 800)
    assert error is not None


def test_a_transposed_pair_is_rejected(tool):
    """A 1280x800 image: (400, 1100) is only reachable by swapping u and v."""
    assert tool.pixel_bounds_error([pair(400, 1100)], 1280, 800) is not None
