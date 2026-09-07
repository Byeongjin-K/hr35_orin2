# GLIM: the candidate the research actually pointed at, installed from its own PPA.
#
# GLIM was ranked first in docs/slam_candidates.md because its README names this exact
# machine - "Tested on Ubuntu 22.04 ... and NVIDIA Jetson Orin (Jetpack 6.1)" - and
# because glim_ext ships GNSS constraints and a ScanContext loop detector, which is the
# whole point of the project. MOLA was tried first only because it looked cheaper to
# install; that turned out to be false (its Humble/arm64 binaries need nanoflann >=
# 1.5.1 while Ubuntu 22.04 ships 1.4.2, and the check is compiled in), so the ranking
# stands unchallenged.
#
# The upstream Docker images are amd64 only, but the PPA carries ARM64 for ubuntu2204,
# so this installs from there rather than building GTSAM 4.3a0 and gtsam_points from
# source. CPU build first: a correct trajectory matters more than speed for a 2668-scan
# offline run, and the CUDA variants (libgtsam-points-cuda12.6-dev, glim-ros-cuda12.6)
# can be swapped in once the pipeline is proven.
FROM ros:humble-ros-base

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl gpg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -s --compressed "https://koide3.github.io/ppa/ubuntu2204/KEY.gpg" \
      | gpg --dearmor > /etc/apt/trusted.gpg.d/koide3_ppa.gpg \
 && echo "deb [signed-by=/etc/apt/trusted.gpg.d/koide3_ppa.gpg] https://koide3.github.io/ppa/ubuntu2204 ./" \
      > /etc/apt/sources.list.d/koide3_ppa.list

RUN apt-get update && apt-get install -y --no-install-recommends \
      libboost-all-dev libglfw3-dev libmetis-dev \
      libgtsam-points-dev \
      ros-humble-glim-ros \
    && rm -rf /var/lib/apt/lists/*
