"""Pinhole camera model for projecting 3D points into the ZED X image.

Pure geometry: no ROS imports, so this is unit-testable standalone.

The one non-obvious responsibility here is reconciling CameraInfo against the
resolution of the image that actually arrives. The ZED wrapper can publish
`general.pub_resolution: CUSTOM`, and a CameraInfo produced for a different
publish size silently ruins every projection. `reconcile_to_image()` rescales
the intrinsics and reports what it had to do so the caller can log it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

_ASPECT_EPS = 1e-3


@dataclass(frozen=True)
class PinholeModel:
    """Intrinsics for a rectified image (no distortion terms by construction)."""

    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    @classmethod
    def from_camera_info_values(
        cls,
        k: "list[float] | tuple[float, ...] | np.ndarray",
        width: int,
        height: int,
    ) -> "PinholeModel":
        """Build from a row-major 3x3 K matrix plus the CameraInfo dimensions."""
        if len(k) != 9:
            raise ValueError(f"K must have 9 elements, got {len(k)}")
        fx, fy = float(k[0]), float(k[4])
        if fx <= 0.0 or fy <= 0.0:
            raise ValueError(f"K has non-positive focal length: fx={fx}, fy={fy}")
        if width <= 0 or height <= 0:
            raise ValueError(f"CameraInfo has empty size: {width}x{height}")
        return cls(
            fx=fx,
            fy=fy,
            cx=float(k[2]),
            cy=float(k[5]),
            width=int(width),
            height=int(height),
        )

    def reconcile_to_image(
        self, image_width: int, image_height: int
    ) -> "tuple[PinholeModel, str | None]":
        """Return intrinsics valid for the actual image size, plus a warning.

        The warning is non-None whenever the caller should be told something is
        off: either the sizes disagreed at all, or they disagreed by different
        factors horizontally and vertically (which means the two sources are
        genuinely inconsistent rather than merely scaled).
        """
        if image_width <= 0 or image_height <= 0:
            raise ValueError(f"image has empty size: {image_width}x{image_height}")

        if (image_width, image_height) == (self.width, self.height):
            return self, None

        sx = image_width / self.width
        sy = image_height / self.height
        scaled = replace(
            self,
            fx=self.fx * sx,
            fy=self.fy * sy,
            cx=self.cx * sx,
            cy=self.cy * sy,
            width=image_width,
            height=image_height,
        )

        detail = (
            f"CameraInfo is {self.width}x{self.height} but the image is "
            f"{image_width}x{image_height}; rescaled intrinsics by "
            f"sx={sx:.4f}, sy={sy:.4f}"
        )
        if abs(sx - sy) > _ASPECT_EPS:
            detail += (
                " -- WARNING: aspect ratios differ, so CameraInfo and the image "
                "do not describe the same framing. Trust neither until the ZED "
                "'general.pub_resolution' / 'pub_downscale_factor' settings are checked."
            )
        return scaled, detail

    def project(
        self, points_cam: np.ndarray, min_depth_m: float
    ) -> "tuple[np.ndarray, np.ndarray]":
        """Project camera-frame points to pixels.

        `points_cam` is (N, 3) in the optical convention: +x right, +y down,
        +z forward. Returns `(uv, keep)` where `uv` is (M, 2) float32 pixel
        coordinates and `keep` is the (N,) boolean mask that produced it.
        Points at or behind `min_depth_m` are culled before the divide, so no
        point from behind the camera can ever alias into the frame.
        """
        if points_cam.ndim != 2 or points_cam.shape[1] != 3:
            raise ValueError(f"points_cam must be (N, 3), got {points_cam.shape}")

        depth = points_cam[:, 2]
        in_front = depth > max(min_depth_m, 1e-6)
        if not np.any(in_front):
            return np.empty((0, 2), dtype=np.float32), in_front

        front = points_cam[in_front]
        inv_z = 1.0 / front[:, 2]
        u = self.fx * front[:, 0] * inv_z + self.cx
        v = self.fy * front[:, 1] * inv_z + self.cy

        on_screen = (
            (u >= 0.0) & (u < self.width) & (v >= 0.0) & (v < self.height)
        )

        keep = np.zeros_like(in_front)
        keep[np.flatnonzero(in_front)[on_screen]] = True

        uv = np.stack((u[on_screen], v[on_screen]), axis=1).astype(np.float32)
        return uv, keep
