"""A stored map that does not carry its datum is a map you cannot trust next week.

The failure these tests exist to prevent is silent and expensive: a map saved in the
estimator's arbitrary local frame, reopened in a later session against a datum chosen
somewhere else, and everything quietly sitting hundreds of metres from where it belongs
while every internal distance still looks perfect.
"""

from __future__ import annotations

import numpy as np
import pytest

from excavator_slam.gnss_anchor import enu_from_llh, llh_from_enu
from excavator_slam.map_export import (
    Datum,
    MapFrame,
    load_map,
    map_points_to_enu,
    rebase_to_datum,
    save_map,
)

SITE = Datum(lat_deg=37.239, lon_deg=127.083, alt_m=61.4)
NEARBY = Datum(lat_deg=37.241, lon_deg=127.080, alt_m=58.0)


def _frame(datum=SITE, yaw_rad=0.0):
    return MapFrame(datum=datum, origin_enu=(120.5, -43.25, 2.75), yaw_rad=yaw_rad)


def _points():
    return np.array([[0.0, 0.0, 0.0],
                     [12.5, -3.25, -1.75],
                     [-40.0, 88.125, 4.5]])


def test_a_saved_map_reopens_with_its_points_and_its_frame(tmp_path):
    path = tmp_path / "site.npz"
    save_map(path, _points(), _frame())
    stored = load_map(path)

    assert stored.points == pytest.approx(_points(), abs=1e-3)
    assert stored.frame.datum == SITE
    assert stored.frame.origin_enu == pytest.approx((120.5, -43.25, 2.75), abs=1e-9)
    assert stored.frame.yaw_rad == pytest.approx(0.0, abs=1e-12)


def test_a_map_without_a_recorded_frame_is_refused_rather_than_assumed(tmp_path):
    """The whole point of the format. A bare point array must not load as "probably here"."""
    path = tmp_path / "bare.npz"
    np.savez(path, points=_points().astype(np.float32))
    with pytest.raises(ValueError):
        load_map(path)


def test_rebasing_to_another_datum_leaves_the_ground_where_it_was(tmp_path):
    """Same rock, different arithmetic origin - compared in metres, not degrees.

    A local tangent plane scales degrees by metres-per-degree evaluated AT ITS DATUM, so
    two datums 200 m apart in latitude disagree about the size of a degree of longitude
    by 2.7e-5. Re-basing therefore moves a point 88 m from the origin by about 2 mm. That
    is the honest bound to assert; a tolerance in degrees tight enough to look impressive
    would be pinning the approximation rather than the round trip.
    """
    frame = _frame()
    points = _points()

    before = map_points_to_enu(points, frame)
    rebased = rebase_to_datum(frame, NEARBY)
    after_llh = llh_from_enu(map_points_to_enu(points, rebased), NEARBY.as_tuple())
    after = enu_from_llh(after_llh[:, 0], after_llh[:, 1], after_llh[:, 2],
                         SITE.as_tuple())

    assert after == pytest.approx(before, abs=5e-3)


def test_rebasing_there_and_back_is_the_identity():
    frame = _frame(yaw_rad=0.7)
    there = rebase_to_datum(frame, NEARBY)
    back = rebase_to_datum(there, SITE)

    assert back.origin_enu == pytest.approx(frame.origin_enu, abs=1e-6)
    assert back.yaw_rad == pytest.approx(frame.yaw_rad, abs=1e-12)
    assert back.datum == SITE


def test_the_frame_yaw_rotates_the_map_into_the_compass(tmp_path):
    """A local +x metre under a 90 degree frame yaw has to come out pointing north."""
    frame = MapFrame(datum=SITE, origin_enu=(0.0, 0.0, 0.0), yaw_rad=np.pi / 2.0)
    enu = map_points_to_enu(np.array([[1.0, 0.0, 0.0]]), frame)
    assert enu[0] == pytest.approx(np.array([0.0, 1.0, 0.0]), abs=1e-9)


def test_absolute_coordinates_are_refused_because_float32_cannot_hold_them(tmp_path):
    """Storing UTM or ECEF coordinates raw is the quiet way to lose centimetres.

    float32 spacing grows with magnitude, so a 500 km easting quantises to about 3 cm
    while the same array in site-local metres is exact to well under a millimetre. The
    format stores local metres and says so by refusing anything else.
    """
    path = tmp_path / "utm.npz"
    utm_like = np.array([[322000.0, 4123000.0, 61.4]])
    with pytest.raises(ValueError):
        save_map(path, utm_like, _frame())


def test_a_site_sized_map_survives_the_round_trip_to_the_millimetre(tmp_path):
    """The other half of the same contract: the allowed range really is lossless enough."""
    path = tmp_path / "big.npz"
    rng = np.random.default_rng(0)
    points = rng.uniform(-800.0, 800.0, size=(5000, 3))
    save_map(path, points, _frame())

    assert load_map(path).points == pytest.approx(points, abs=1e-3)
