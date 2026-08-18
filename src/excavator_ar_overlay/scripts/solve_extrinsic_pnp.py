#!/usr/bin/env python3
"""Solve T_camera <- gm_swing_axis from hand-picked correspondences.

Automatic edge alignment was tried four ways on this scene and failed each time:
summing over in-view points rewarded aiming at the densest part of the cloud,
averaging rewarded cropping to the near ground where the track marks are, a
fixed-normaliser version went flat and unstable, and HSV segmentation could not
separate the fence from dry soil because both are bright and desaturated. The
failures are recorded in docs/calibration_session_20260818.md.

Correspondences remove the ambiguity: a handful of points a person can identify
in both the photo and the cloud pins the pose directly, and solvePnP is a solved
problem. Six well-spread points are enough; more is better.

Usage
-----
1. Render a numbered grid over a capture to read pixel coordinates:
       python3 solve_extrinsic_pnp.py --grid pose06
2. Read 3D coordinates for the same features out of the cloud. The session notes
   list structures already fitted in gm_swing_axis coordinates:
       ground plane  z = 0.155 m, normal [0.108, 0.081, 0.991]
       fence plane   x = 7.91 m,  normal [0.993, 0.022, -0.117]
   so a point on the fence base line is (7.91, y, 0.155) for whatever y.
3. Put the pairs in a JSON file and solve:
       python3 solve_extrinsic_pnp.py --pairs pairs.json --pose pose06

Pairs file format:
    {"points": [{"px": [337, 190], "xyz": [7.91, 1.2, 0.155], "note": "post 1 base"},
                 ...]}
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

DATA = os.path.expanduser("~/data/lidar_cam_calib")

# What the user reports about the physical install, used as a sanity gate rather
# than as a constraint on the solve: cabin roof, slightly forward and left of the
# swing axis, 2-3 m up.
PRIOR_LO = np.array([0.0, -0.3, 2.0])
PRIOR_HI = np.array([1.6, 1.2, 3.0])


def find_pose(tag: str) -> str:
    hits = sorted(glob.glob(f"{DATA}/{tag}*_meta.json"))
    if not hits:
        sys.exit(f"no capture matching {tag!r} under {DATA}")
    return hits[0].replace("_meta.json", "")


def draw_grid(stem: str, step: int = 100) -> str:
    img = cv2.imread(f"{stem}_image.jpg")
    h, w = img.shape[:2]
    vis = img.copy()
    for x in range(0, w, step):
        cv2.line(vis, (x, 0), (x, h), (0, 255, 255), 1)
        for thick, col in ((3, (0, 0, 0)), (1, (0, 255, 255))):
            cv2.putText(vis, str(x), (x + 3, 22), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, col, thick, cv2.LINE_AA)
    for y in range(0, h, step):
        cv2.line(vis, (0, y), (w, y), (0, 255, 255), 1)
        for thick, col in ((3, (0, 0, 0)), (1, (0, 255, 255))):
            cv2.putText(vis, str(y), (4, y - 4), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, col, thick, cv2.LINE_AA)
    out = f"{stem}_grid.png"
    cv2.imwrite(out, vis)
    return out


def solve(stem: str, pairs: "list[dict]") -> None:
    meta = json.load(open(f"{stem}_meta.json"))
    K = np.array(meta["camera_info"]["k"], dtype=np.float64).reshape(3, 3)
    obj = np.array([p["xyz"] for p in pairs], dtype=np.float64)
    img = np.array([p["px"] for p in pairs], dtype=np.float64)

    if obj.shape[0] < 4:
        sys.exit(f"need at least 4 correspondences, got {obj.shape[0]}")

    ok, rvec, tvec = cv2.solvePnP(
        obj, img, K, np.zeros(5), flags=cv2.SOLVEPNP_SQPNP
    )
    if not ok:
        sys.exit("solvePnP failed")
    if obj.shape[0] >= 6:
        rvec, tvec = cv2.solvePnPRefineLM(obj, img, K, np.zeros(5), rvec, tvec)

    R, _ = cv2.Rodrigues(rvec)
    C = (-R.T @ tvec).ravel()

    proj, _ = cv2.projectPoints(obj, rvec, tvec, K, np.zeros(5))
    err = np.linalg.norm(proj.reshape(-1, 2) - img, axis=1)

    print(f"correspondences : {obj.shape[0]}")
    print(f"reprojection err: mean {err.mean():.2f} px, max {err.max():.2f} px")
    for p, e in zip(pairs, err):
        print(f"   {e:6.2f} px  {p.get('note', '')}")

    print(f"\ncamera position in gm_swing_axis: "
          f"[{C[0]:+.4f}, {C[1]:+.4f}, {C[2]:+.4f}] m")
    inside = bool(np.all(C >= PRIOR_LO) and np.all(C <= PRIOR_HI))
    print(f"  within the reported install envelope: {inside}"
          f"{'' if inside else '   <-- check the correspondences'}")

    fwd = R[2]
    print(f"  look direction {np.round(fwd, 4)}  "
          f"pitch below horizon {np.degrees(np.arcsin(-fwd[2])):.1f} deg  "
          f"yaw {np.degrees(np.arctan2(fwd[1], fwd[0])):.1f} deg")

    Rt = R.T
    rx = np.arctan2(Rt[2, 1], Rt[2, 2])
    ry = np.arctan2(-Rt[2, 0], np.hypot(Rt[0, 0], Rt[1, 0]))
    rz = np.arctan2(Rt[1, 0], Rt[0, 0])
    print("\nparent=gm_swing_axis  child=zedx_cabin_left_camera_optical_frame")
    print(f"  xyz: [{C[0]:.4f}, {C[1]:.4f}, {C[2]:.4f}]")
    print(f"  rpy: [{rx:.6f}, {ry:.6f}, {rz:.6f}]")

    if obj.shape[0] >= 6:
        print("\nleave-one-out:")
        worst_c, worst_r = 0.0, 0.0
        for i in range(obj.shape[0]):
            keep = [j for j in range(obj.shape[0]) if j != i]
            ok2, rv2, tv2 = cv2.solvePnP(obj[keep], img[keep], K, np.zeros(5),
                                         flags=cv2.SOLVEPNP_SQPNP)
            if not ok2:
                continue
            R2, _ = cv2.Rodrigues(rv2)
            C2 = (-R2.T @ tv2).ravel()
            dr = np.degrees(np.arccos(np.clip((np.trace(R.T @ R2) - 1) / 2, -1, 1)))
            dc = float(np.linalg.norm(C2 - C))
            worst_r, worst_c = max(worst_r, dr), max(worst_c, dc)
            print(f"  drop {i}: drot {dr:5.2f} deg  dpos {dc:.3f} m  "
                  f"{pairs[i].get('note', '')}")
        verdict = "PASS" if worst_r <= 0.72 and worst_c <= 0.075 else "SHORT"
        print(f"  worst {worst_r:.2f} deg / {worst_c:.3f} m "
              f"vs 0.72 deg / 0.075 m  -> {verdict}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid", metavar="POSE", help="write a coordinate grid overlay")
    ap.add_argument("--pairs", metavar="JSON", help="correspondence file")
    ap.add_argument("--pose", default="pose06", help="capture to solve against")
    args = ap.parse_args()

    if args.grid:
        print(draw_grid(find_pose(args.grid)))
        return
    if not args.pairs:
        ap.error("give --grid to read coordinates, or --pairs to solve")
    solve(find_pose(args.pose), json.load(open(args.pairs))["points"])


if __name__ == "__main__":
    main()
