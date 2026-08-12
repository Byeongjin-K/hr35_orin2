"""Drawing primitives for the AR overlay. Pure OpenCV/numpy, no ROS imports.

The legend and the HUD are drawn *into* the frame rather than published
alongside it: the consuming GUI panel is only ~360 px wide and has nowhere to
put an external legend.
"""

from __future__ import annotations

import cv2
import numpy as np

_FONT = cv2.FONT_HERSHEY_SIMPLEX
_SHADOW = (0, 0, 0)
_TEXT = (255, 255, 255)


def depth_colors(depths: np.ndarray, near_m: float, far_m: float) -> np.ndarray:
    """Map distances to BGR colors via TURBO: near = blue, far = red."""
    if far_m <= near_m:
        raise ValueError(f"far_m ({far_m}) must exceed near_m ({near_m})")
    if depths.size == 0:
        return np.empty((0, 3), dtype=np.uint8)

    normalized = np.clip((depths - near_m) / (far_m - near_m), 0.0, 1.0)
    keys = (normalized * 255.0).astype(np.uint8).reshape(-1, 1)
    return cv2.applyColorMap(keys, cv2.COLORMAP_TURBO).reshape(-1, 3)


def draw_points(
    canvas: np.ndarray,
    uv: np.ndarray,
    colors: np.ndarray,
    radius: int,
) -> None:
    """Stamp projected points onto the canvas.

    radius <= 0 writes single pixels with a vectorised scatter, which is an
    order of magnitude faster than per-point cv2.circle for a 65k-point cloud.
    """
    if uv.shape[0] == 0:
        return

    height, width = canvas.shape[:2]
    cols = np.clip(uv[:, 0].astype(np.int32), 0, width - 1)
    rows = np.clip(uv[:, 1].astype(np.int32), 0, height - 1)

    if radius <= 0:
        canvas[rows, cols] = colors
        return

    for col, row, color in zip(cols, rows, colors):
        cv2.circle(
            canvas,
            (int(col), int(row)),
            radius,
            (int(color[0]), int(color[1]), int(color[2])),
            -1,
            lineType=cv2.LINE_AA,
        )


def put_text(
    canvas: np.ndarray,
    text: str,
    origin: "tuple[int, int]",
    scale: float,
    thickness: int = 1,
    color: "tuple[int, int, int]" = _TEXT,
) -> None:
    """Draw text with a dark outline so it stays legible over bright terrain."""
    cv2.putText(
        canvas, text, origin, _FONT, scale, _SHADOW, thickness + 2, cv2.LINE_AA
    )
    cv2.putText(canvas, text, origin, _FONT, scale, color, thickness, cv2.LINE_AA)


def draw_hud(
    canvas: np.ndarray,
    lines: "list[str]",
    scale: float,
    margin: int = 8,
) -> None:
    """Top-left status block over a translucent plate."""
    if not lines:
        return

    line_h = int(round(30 * scale))
    box_h = margin + line_h * len(lines) + margin // 2
    box_w = margin + int(
        round(max(cv2.getTextSize(t, _FONT, scale, 1)[0][0] for t in lines))
    ) + margin

    box_w = min(box_w, canvas.shape[1])
    box_h = min(box_h, canvas.shape[0])
    plate = canvas[0:box_h, 0:box_w]
    cv2.addWeighted(plate, 0.35, np.zeros_like(plate), 0.65, 0.0, dst=plate)

    for index, text in enumerate(lines):
        baseline = margin + line_h * (index + 1) - int(round(8 * scale))
        put_text(canvas, text, (margin, baseline), scale)


def draw_depth_legend(
    canvas: np.ndarray,
    near_m: float,
    far_m: float,
    scale: float,
    margin: int = 8,
) -> None:
    """Horizontal colour bar with end labels, bottom-right, baked into the frame."""
    height, width = canvas.shape[:2]
    bar_w = max(60, int(width * 0.34))
    bar_h = max(6, int(round(10 * scale * 1.6)))
    label_h = int(round(26 * scale))

    x1 = width - margin
    x0 = max(0, x1 - bar_w)
    y1 = height - margin - label_h
    y0 = max(0, y1 - bar_h)
    if x1 - x0 < 8 or y1 - y0 < 3:
        return

    ramp = np.linspace(0, 255, x1 - x0, dtype=np.uint8).reshape(1, -1)
    ramp = cv2.applyColorMap(ramp, cv2.COLORMAP_TURBO)
    canvas[y0:y1, x0:x1] = np.repeat(ramp, y1 - y0, axis=0)
    cv2.rectangle(canvas, (x0, y0), (x1 - 1, y1 - 1), _SHADOW, 1)

    text_y = min(height - 2, y1 + label_h - int(round(6 * scale)))
    put_text(canvas, f"{near_m:.0f}m", (x0, text_y), scale)
    far_label = f"{far_m:.0f}m"
    far_w = cv2.getTextSize(far_label, _FONT, scale, 1)[0][0]
    put_text(canvas, far_label, (max(x0, x1 - far_w), text_y), scale)


def draw_banner(canvas: np.ndarray, text: str, scale: float) -> None:
    """Centred warning used when the overlay cannot be produced."""
    height, width = canvas.shape[:2]
    text_w, text_h = cv2.getTextSize(text, _FONT, scale, 2)[0]
    origin = ((width - text_w) // 2, (height + text_h) // 2)
    put_text(canvas, text, origin, scale, thickness=2, color=(0, 220, 255))


def draw_filled_polygons(
    canvas: np.ndarray,
    polygons: "list[np.ndarray]",
    colors: "list[tuple[int, int, int]]",
    alpha: float,
    outline_thickness: int,
) -> None:
    """Translucent fills with opaque outlines.

    The fills go onto one scratch layer and are blended in a single pass, so
    overlapping cells do not compound into an opaque blob and hide the terrain
    the operator is trying to check the plan against.
    """
    if not polygons:
        return

    alpha = float(np.clip(alpha, 0.0, 1.0))
    if alpha > 0.0:
        fills = np.zeros_like(canvas)
        touched = np.zeros(canvas.shape[:2], dtype=np.uint8)
        for points, color in zip(polygons, colors):
            cv2.fillConvexPoly(fills, points, color, lineType=cv2.LINE_AA)
            cv2.fillConvexPoly(touched, points, 1, lineType=cv2.LINE_AA)
        mask = touched.astype(bool)
        if mask.any():
            canvas[mask] = (
                canvas[mask] * (1.0 - alpha) + fills[mask] * alpha
            ).astype(np.uint8)

    if outline_thickness > 0:
        for points, color in zip(polygons, colors):
            cv2.polylines(
                canvas,
                [points],
                True,
                color,
                outline_thickness,
                lineType=cv2.LINE_AA,
            )


def draw_start_marker(
    canvas: np.ndarray,
    center: "tuple[int, int]",
    radius: int,
    label: str,
    scale: float,
) -> None:
    """Ring plus label on the dig start cell."""
    if radius <= 0:
        return
    cv2.circle(canvas, center, radius + 2, _SHADOW, 3, lineType=cv2.LINE_AA)
    cv2.circle(canvas, center, radius, (255, 255, 255), 2, lineType=cv2.LINE_AA)
    cv2.drawMarker(
        canvas, center, (255, 255, 255), cv2.MARKER_CROSS, radius, 1, cv2.LINE_AA
    )
    if label:
        put_text(canvas, label, (center[0] + radius + 4, center[1] - 4), scale)
