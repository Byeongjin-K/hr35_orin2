"""Reading GLIM's on-disk map dump, which is the only producer the map format has.

A dump is one numbered directory per submap. The bit that matters:

  data.txt            a text header whose "T_world_origin:" block is the 4x4 pose that
                      puts this submap's points into the map frame
  points_compact.bin  the submap cloud, raw little-endian float32 x,y,z with no header

The binary layout is asserted rather than assumed: a file whose length is not a multiple
of three floats is a different format, and reading it as points would silently produce a
map made of shredded coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

POSE_KEY = "T_world_origin:"


@dataclass(frozen=True)
class Submap:
    identifier: str
    points: npt.NDArray[np.float64]
    pose_world_origin: npt.NDArray[np.float64]

    def points_in_map(self):
        rotation = self.pose_world_origin[:3, :3]
        translation = self.pose_world_origin[:3, 3]
        return self.points @ rotation.T + translation


def parse_pose(text, key=POSE_KEY):
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith(key):
            rows = [np.fromstring(row, sep=" ") for row in lines[index + 1:index + 5]]
            if any(row.size != 4 for row in rows):
                raise ValueError(f"{key} is not followed by four rows of four numbers")
            return np.asarray(rows, dtype=float)
    raise ValueError(f"no {key} block found")


def read_submap(directory):
    directory = Path(directory)
    header = directory / "data.txt"
    binary = directory / "points_compact.bin"
    if not header.exists() or not binary.exists():
        raise ValueError(f"{directory} is not a GLIM submap dump: data.txt or "
                         "points_compact.bin is missing")

    raw = np.fromfile(binary, dtype=np.float32)
    if raw.size == 0 or raw.size % 3 != 0:
        raise ValueError(f"{binary} holds {raw.size} float32 values, which is not a whole "
                         "number of xyz points - this is not the compact point format")

    return Submap(identifier=directory.name,
                  points=raw.reshape(-1, 3).astype(float),
                  pose_world_origin=parse_pose(header.read_text()))


def read_dump(dump_dir):
    """Every submap, in id order. A dump with none is an error, not an empty map."""
    directories = sorted(path for path in Path(dump_dir).iterdir()
                         if path.is_dir() and (path / "points_compact.bin").exists())
    if not directories:
        raise ValueError(f"{dump_dir} contains no submap directories")
    return [read_submap(path) for path in directories]


def dump_points_in_map(dump_dir):
    return np.concatenate([submap.points_in_map() for submap in read_dump(dump_dir)])
