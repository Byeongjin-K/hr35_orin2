"""The GNSS-anchor chain, pinned against the arithmetic that actually runs in the field.

The thing SLAM has to beat is the deployed open-loop GNSS anchor, so the baseline
trajectory has to be the SAME arithmetic that pipeline runs - not a fresh derivation
that merely looks similar. Values in test/data/anchor_reference.json were produced by
executing the functions of gridmap-shake/gridmap_diag/replay_global_map.py, an
independent numpy port of the deployed C++ global_map_math.hpp that an earlier session
checked against recorded bags. Writing the expectations by hand from the same formulas
this module implements would only restate the port and could not fail; a cross
implementation therefore has to supply them.

A disagreement here means the port drifted from the pipeline, which is exactly what
would make a baseline-versus-SLAM number meaningless.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from excavator_slam.gnss_anchor import (
    AnchorParams,
    cab_heading_from_published,
    compute_anchor,
    enu_from_llh,
    llh_from_enu,
    map_to_world,
)

REFERENCE = json.loads((Path(__file__).parent / "data" / "anchor_reference.json").read_text())
DATUM = tuple(REFERENCE["datum"])
PARAMS = AnchorParams(**REFERENCE["params"])
PROBE = np.array(REFERENCE["probe_points_map"], dtype=float)


def _anchor(case):
    cab = cab_heading_from_published(case["heading_published"], case["mirrored"])
    antenna = enu_from_llh(case["lat"], case["lon"], case["alt"], DATUM)
    return antenna, compute_anchor(antenna, float(cab), case["swing_deg"], PARAMS)


@pytest.mark.parametrize("case", REFERENCE["cases"])
def test_antenna_enu_matches_the_field_implementation(case):
    antenna, _ = _anchor(case)
    assert antenna == pytest.approx(case["antenna_enu"], abs=1e-9)


@pytest.mark.parametrize("case", REFERENCE["cases"])
def test_mirrored_convention_matches_the_field_implementation(case):
    cab = cab_heading_from_published(case["heading_published"], case["mirrored"])
    assert float(cab) == pytest.approx(case["cab_heading_deg"], abs=1e-12)


@pytest.mark.parametrize("case", REFERENCE["cases"])
def test_anchor_origin_and_yaw_match_the_field_implementation(case):
    _, (origin, yaw) = _anchor(case)
    assert origin == pytest.approx(case["origin_enu"], abs=1e-9)
    assert yaw == pytest.approx(case["yaw_rad"], abs=1e-12)


@pytest.mark.parametrize("case", REFERENCE["cases"])
def test_map_to_world_matches_the_field_implementation(case):
    _, (origin, yaw) = _anchor(case)
    world = map_to_world(PROBE, origin, yaw)
    assert world == pytest.approx(np.array(case["probe_points_world"]), abs=1e-9)


def test_enu_round_trips_through_the_datum():
    case = REFERENCE["cases"][1]
    enu = enu_from_llh(case["lat"], case["lon"], case["alt"], DATUM)
    lat, lon, alt = llh_from_enu(enu, DATUM)
    assert (lat, lon, alt) == pytest.approx((case["lat"], case["lon"], case["alt"]), abs=1e-9)
