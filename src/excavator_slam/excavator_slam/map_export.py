"""Persisting a SLAM map together with the datum that gives it a place on Earth.

GLIM's map lives in a frame whose origin is wherever the estimator happened to start and
whose yaw is wherever the machine happened to be pointing. That is fine inside one run
and useless across runs: every internal distance stays perfect while the whole map sits
somewhere arbitrary. So a stored map here is always a pair - local points plus the
MapFrame that ties them to a site datum - and loading refuses a file that has lost one.

WHY POINTS ARE STORED LOCAL AND float32
---------------------------------------
float32 spacing grows with magnitude: the quantisation error is about |x| * 2**-24, so a
500 km UTM easting lands on a 3 cm grid while the same terrain in site-local metres is
exact to microns. Baking absolute coordinates into the array is the quiet way to lose
centimetres from a map built to millimetre-level registration, so save_map refuses
anything beyond the magnitude at which the error reaches a centimetre and tells the
caller to move the offset into the frame's origin instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from .gnss_anchor import enu_from_llh, llh_from_enu, map_to_world

CENTIMETRE_M = 0.01
FLOAT32_MANTISSA_STEPS = 2 ** 24
LOCAL_EXTENT_LIMIT_M = CENTIMETRE_M * FLOAT32_MANTISSA_STEPS


@dataclass(frozen=True)
class Datum:
    lat_deg: float
    lon_deg: float
    alt_m: float

    def as_tuple(self):
        return (self.lat_deg, self.lon_deg, self.alt_m)


@dataclass(frozen=True)
class MapFrame:
    """Where a map's local origin sits, and which way it faces, in a datum's ENU."""

    datum: Datum
    origin_enu: tuple[float, float, float]
    yaw_rad: float


@dataclass(frozen=True)
class StoredMap:
    points: npt.NDArray[np.float64]
    frame: MapFrame


def map_points_to_enu(points_map, frame):
    return map_to_world(points_map, frame.origin_enu, frame.yaw_rad)


def rebase_to_datum(frame, datum):
    """The same ground, expressed against a different datum.

    The yaw carries over unchanged. Two datums a few hundred metres apart differ in
    meridian convergence by well under a microradian, which is orders of magnitude below
    the heading uncertainty the anchor already carries; the local tangent plane's scale
    difference is the term that actually shows, and it is millimetres at site range.
    """
    origin_llh = llh_from_enu(frame.origin_enu, frame.datum.as_tuple())
    origin_enu = enu_from_llh(float(origin_llh[0]), float(origin_llh[1]),
                              float(origin_llh[2]), datum.as_tuple())
    return MapFrame(datum=datum,
                    origin_enu=(float(origin_enu[0]), float(origin_enu[1]),
                                float(origin_enu[2])),
                    yaw_rad=frame.yaw_rad)


def save_map(path, points_map, frame):
    points = np.asarray(points_map, dtype=float)
    if points.ndim != 2 or points.shape[1] < 3:
        raise ValueError(f"map points must be an Nx3 array, got shape {points.shape}")
    points = points[:, :3]

    extent = float(np.max(np.abs(points))) if points.size else 0.0
    if extent > LOCAL_EXTENT_LIMIT_M:
        raise ValueError(
            f"map coordinates reach {extent:.0f} m, past the {LOCAL_EXTENT_LIMIT_M:.0f} m "
            "where float32 storage starts costing more than a centimetre. These look "
            "like absolute coordinates: keep the points site-local and put the offset in "
            "the frame's origin_enu.")

    # Written through a file handle, not a path: given a path, savez APPENDS ".npz" when
    # it is missing, so "--out site_map" would write site_map.npz while every message and
    # every reader still says site_map. A handle makes save and load agree on any name.
    with open(path, "wb") as handle:
        np.savez_compressed(handle,
                            points=points.astype(np.float32),
                            frame=json.dumps(_frame_to_dict(frame)))


def load_map(path):
    with np.load(path, allow_pickle=False) as data:
        if "frame" not in data.files:
            raise ValueError(
                f"{path} stores points with no map frame, so there is nothing to say "
                "where they are. Re-export it with save_map.")
        frame = _frame_from_dict(json.loads(str(data["frame"].item())))
        points = np.asarray(data["points"], dtype=float)
    return StoredMap(points=points, frame=frame)


def _frame_to_dict(frame):
    return {
        "datum": {"lat_deg": frame.datum.lat_deg,
                  "lon_deg": frame.datum.lon_deg,
                  "alt_m": frame.datum.alt_m},
        "origin_enu": [float(value) for value in frame.origin_enu],
        "yaw_rad": float(frame.yaw_rad),
    }


def _frame_from_dict(raw):
    origin = raw["origin_enu"]
    return MapFrame(datum=Datum(**raw["datum"]),
                    origin_enu=(float(origin[0]), float(origin[1]), float(origin[2])),
                    yaw_rad=float(raw["yaw_rad"]))
