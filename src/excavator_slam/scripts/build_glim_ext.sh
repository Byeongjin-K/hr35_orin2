#!/usr/bin/env bash
# Build the glim_ext modules this project needs, against the GLIM already in the image.
#
# The PPA ships glim and glim_ros but NOT glim_ext, so the GNSS factor module and the
# ScanContext loop detector simply do not exist in the runtime image. Everything needed
# to build them IS there: gtsam and gtsam_points headers under /usr/local/include, glim's
# cmake config under /opt/ros/humble/share/glim, Eigen at /usr/include/eigen3.
#
# WHAT THIS DOES NOT BUILD, and why: ScanContext needs PCL, and the image carries zero
# libpcl packages. Adding PCL to the runtime image for a loop detector that cannot be
# validated without a drive-away recording is not a trade worth making yet - measured
# here so the next person does not rediscover it. Everything else is switched off because
# it is either unrelated (ORB-SLAM, FAST-LIO2, DBoW) or not asked for.
#
# The module .so must be on LD_LIBRARY_PATH and named in config_ros.json's
# extension_modules. Config wiring lives in config/glim_cabin/config_ext.json.
set -euo pipefail

IMAGE=${IMAGE:-excavator-slam-glim:humble}
SRC=${SRC:-/home/kimm/data/build/glim_ext}
OUT=${OUT:-/home/kimm/data/build/glim_ext_build}

if [ ! -d "$SRC/.git" ]; then
  git clone --depth 1 https://github.com/koide3/glim_ext.git "$SRC"
fi
# Only ScanContext's submodule is small; the others pull ORB-SLAM3 and DBoW and are not
# built here, so they stay uninitialised on purpose.
git -C "$SRC" submodule update --init \
  modules/mapping/scan_context_loop_detector/thirdparty/scancontext

mkdir -p "$OUT"
docker run --rm --cpus "${CPUS:-2}" --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$SRC":/src:ro -v "$OUT":/build \
  --entrypoint bash "$IMAGE" -lc '
    set -e
    source /opt/ros/humble/setup.bash
    nice -n 19 cmake -B /build -S /src -DCMAKE_BUILD_TYPE=Release \
      -DENABLE_GNSS=ON \
      -DENABLE_SCAN_CONTEXT=OFF -DENABLE_DBOW=OFF -DENABLE_ORBSLAM=OFF \
      -DENABLE_FASTLIO2=OFF -DENABLE_VELSUPP=OFF -DENABLE_IMUVAL=OFF \
      -DENABLE_IMUPRED=OFF -DENABLE_GRAVITY=OFF -DENABLE_DESKEWING=OFF \
      -DENABLE_FLATEARTHER=OFF
    nice -n 19 cmake --build /build -j"${JOBS:-2}"
  '

echo "BUILT"
find "$OUT" -name '*.so' | sed 's|^|  |'
