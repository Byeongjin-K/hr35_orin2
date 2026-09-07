"""The GNSS-anchor chain the deployed global map runs, as numpy.

DELIBERATELY ROS-FREE, like revisit_metric: plain numbers in, plain numbers out, so
the arithmetic can be pinned by a unit test without a bag or a node.

This is a PORT, not an improvement. It reproduces what rn_global_map actually does
today (ontariotech_koceti_jetson_docker, include/rn_grid_map/global_map_math.hpp),
because its job is to produce the BASELINE trajectory that SLAM has to beat. Two of
its quirks are therefore preserved on purpose:

  * the antenna lever arm is rotated by cab yaw ONLY, with no roll or pitch, and
  * the anchor height is then overwritten with the raw antenna height,

which together drop the r*sin(roll)*cos(swing) term. A previous session measured that
term at 3.2 cm peak-to-peak at 5 degrees of roll and 9.5 cm at 15 degrees, and it is
one of the reasons revisits do not line up. Fixing it here would flatter the baseline
and understate what SLAM is worth, so the fix does not belong in this file.

Angle conventions, which are the easiest thing to get wrong here:

  heading  compass bearing, north = 0, clockwise. What the GNSS publishes.
  yaw      ENU plane angle, east = 0, counter-clockwise. What rotations need.
           yaw = 90 - heading.

Frames:

  world  ENU of the datum. x east, y north, z up.
  map    the voxeliser's output frame: gravity aligned, origin at the swing axis on
         the ground, x forward along the undercarriage, y left, z up.
  cab    the superstructure. map rotated by the swing angle. The GNSS antenna sits
         here, so the antenna circles the swing axis as the cab turns, which is what
         the lever arm corrects for.

A local ENU tangent plane is used rather than UTM for the same reason the C++ does:
over a 100 m site the flat-earth error is under a tenth of a millimetre, while UTM
eastings near 5e5 m quantise to about 3 cm in float32 - a fifth of a 0.15 m cell.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

WGS84_SEMI_MAJOR_AXIS_M = 6378137.0
WGS84_FLATTENING = 1.0 / 298.257223563


def meters_per_degree(lat_deg):
    """Metres per degree of latitude and of longitude at a given latitude.

    The meridional and prime-vertical radii of curvature, not a constant 111320,
    so the scale follows latitude instead of being right in only one place.
    """
    e2 = WGS84_FLATTENING * (2.0 - WGS84_FLATTENING)
    sin_lat = np.sin(np.radians(lat_deg))
    denominator = 1.0 - e2 * sin_lat * sin_lat
    m_lat = np.radians(1.0) * WGS84_SEMI_MAJOR_AXIS_M * (1.0 - e2) / denominator ** 1.5
    m_lon = (np.radians(1.0) * WGS84_SEMI_MAJOR_AXIS_M / np.sqrt(denominator)
             * np.cos(np.radians(lat_deg)))
    return float(m_lat), float(m_lon)


def enu_from_llh(lat_deg, lon_deg, alt_m, datum):
    """Geodetic position to datum-relative ENU metres. Scalars or arrays."""
    datum_lat, datum_lon, datum_alt = datum
    m_lat, m_lon = meters_per_degree(datum_lat)
    return np.stack([
        (np.asarray(lon_deg, float) - datum_lon) * m_lon,
        (np.asarray(lat_deg, float) - datum_lat) * m_lat,
        np.asarray(alt_m, float) - datum_alt,
    ], axis=-1)


def llh_from_enu(enu, datum):
    """The inverse, for exporting a map or checking the round trip."""
    datum_lat, datum_lon, datum_alt = datum
    m_lat, m_lon = meters_per_degree(datum_lat)
    enu = np.asarray(enu, float)
    return np.stack([
        datum_lat + enu[..., 1] / m_lat,
        datum_lon + enu[..., 0] / m_lon,
        datum_alt + enu[..., 2],
    ], axis=-1)


def yaw_rad_from_heading_deg(heading_deg):
    """Compass bearing to ENU yaw. By definition yaw = 90 - heading."""
    return np.radians(90.0 - np.asarray(heading_deg, float))


def rot_z(yaw_rad):
    """Rotation about the vertical only, so gravity alignment survives it."""
    cos_yaw, sin_yaw = np.cos(yaw_rad), np.sin(yaw_rad)
    return np.array([[cos_yaw, -sin_yaw, 0.0],
                     [sin_yaw, cos_yaw, 0.0],
                     [0.0, 0.0, 1.0]])


def cab_heading_from_published(heading_deg, mirrored):
    """Published heading to true cab bearing.

    The upstream GNSS node publishes 180 - heading_raw, and undoing that mirror has
    two candidate inverses exactly 180 degrees apart which stationary data cannot
    tell apart. The deployed node carries the same flag; a previous session resolved
    it per bag by terrain self-consistency, so it stays an explicit argument here
    rather than a constant.
    """
    heading = np.asarray(heading_deg, float)
    return (180.0 - heading) if mirrored else (-heading)


@dataclass
class AnchorParams:
    """Same meaning and defaults as C++ global_map::AnchorParams.

    lever_x / lever_y come from the 2026-08-11 RTK swing calibration (the antenna
    traces a circle of radius 0.1838 m about the swing axis). swing_to_heading_sign
    is -1 because the swing signal the node consumes is itself derived from heading,
    so the sign has to cancel it for the map bearing to hold still.
    """

    lever_x: float = 0.1734
    lever_y: float = -0.0611
    lever_z: float = 0.0
    swing_to_heading_sign: float = -1.0
    heading_offset_deg: float = 0.0
    antenna_height_m: float = 0.0


def compute_anchor(antenna_enu, cab_heading_deg, swing_deg, params):
    """map -> world anchor: the ENU origin of the map frame and its yaw.

    Returns (origin_enu, yaw_rad). See the module docstring for why the lever arm is
    rotated by yaw alone and the height is then overwritten: that is the deployed
    behaviour and the baseline must show it.
    """
    antenna_enu = np.asarray(antenna_enu, float)
    cab_yaw = yaw_rad_from_heading_deg(cab_heading_deg)
    lever_enu = rot_z(cab_yaw) @ np.array([params.lever_x, params.lever_y, params.lever_z])
    origin = antenna_enu - lever_enu
    origin[2] = antenna_enu[2] - params.antenna_height_m
    undercarriage_heading = (cab_heading_deg
                             - params.swing_to_heading_sign * swing_deg
                             + params.heading_offset_deg)
    return origin, float(yaw_rad_from_heading_deg(undercarriage_heading))


def map_to_world(points_map, origin_enu, yaw_rad):
    """(N,3) points in the map frame to (N,3) world ENU."""
    return np.asarray(points_map, float) @ rot_z(yaw_rad).T + np.asarray(origin_enu, float)
