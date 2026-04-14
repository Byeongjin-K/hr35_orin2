#!/bin/bash
#
# ROS2 Bag GUI — Jetson AGX Orin 설치 스크립트
#
# 전제조건:
#   - JetPack 6.x (Ubuntu 22.04, Python 3.10)
#   - ROS2 Humble 설치됨
#   - ZED SDK 설치됨 (ZEDx 사용 중)
#   - Ouster 드라이버 설치됨 (ouster_ros)
#
# 사용법:
#   chmod +x setup_jetson.sh
#   ./setup_jetson.sh
#

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()  { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================="
echo " ROS2 Bag GUI — Jetson AGX Orin Setup"
echo "============================================="
echo ""

# -----------------------------------------------
# 1. 환경 확인
# -----------------------------------------------
echo "--- [1/6] 환경 확인 ---"

# Python
PYTHON_BIN=""
if command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
else
    fail "python3을 찾을 수 없습니다."
fi
PY_VER=$($PYTHON_BIN -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
log "Python: $PY_VER ($($PYTHON_BIN --version))"

PY_MAJOR=$($PYTHON_BIN -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON_BIN -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    fail "Python 3.10 이상이 필요합니다. (현재: $PY_VER)"
fi

# ROS2
if [ -z "${ROS_DISTRO:-}" ]; then
    # 자동 source 시도
    if [ -f /opt/ros/humble/setup.bash ]; then
        source /opt/ros/humble/setup.bash
        log "ROS2 Humble 자동 source 완료"
    else
        fail "ROS_DISTRO가 설정되지 않았습니다. 'source /opt/ros/humble/setup.bash' 먼저 실행하세요."
    fi
fi
log "ROS2: $ROS_DISTRO"

# rosbag2_py 확인
$PYTHON_BIN -c "import rosbag2_py" 2>/dev/null || fail "rosbag2_py를 import할 수 없습니다. ros-humble-rosbag2 패키지를 확인하세요."
log "rosbag2_py: OK"

# 아키텍처
ARCH=$(uname -m)
log "Architecture: $ARCH"

# ZED SDK 확인 (optional)
ZED_OK=false
if $PYTHON_BIN -c "import pyzed.sl" 2>/dev/null; then
    ZED_OK=true
    log "ZED SDK (pyzed): OK"
else
    warn "ZED SDK (pyzed)를 import할 수 없습니다. SVO2 녹화/추출 기능은 비활성화됩니다."
fi

echo ""

# -----------------------------------------------
# 2. 시스템 패키지 설치
# -----------------------------------------------
echo "--- [2/6] 시스템 패키지 설치 ---"

sudo apt-get update -qq

# Qt6 / PySide6 의존성
# aarch64에서 pip PySide6 wheel이 없으므로 시스템 패키지 사용
PYSIDE6_PKGS=(
    python3-pyside6.qtcore
    python3-pyside6.qtgui
    python3-pyside6.qtwidgets
)

# PySide6 시스템 패키지 설치 시도
PYSIDE6_INSTALLED=false
if apt-cache show python3-pyside6.qtcore &>/dev/null 2>&1; then
    sudo apt-get install -y "${PYSIDE6_PKGS[@]}" && PYSIDE6_INSTALLED=true
fi

if [ "$PYSIDE6_INSTALLED" = false ]; then
    warn "시스템 PySide6 패키지를 찾을 수 없습니다. pip로 설치를 시도합니다..."
    # Qt6 빌드 의존성 설치 후 pip 빌드
    sudo apt-get install -y \
        qt6-base-dev \
        libqt6widgets6 \
        libqt6gui6 \
        libqt6core6 \
        libgl1-mesa-dev \
        2>/dev/null || true
    $PYTHON_BIN -m pip install --user PySide6 2>/dev/null || {
        warn "PySide6 pip 설치도 실패했습니다. PyQt6로 대체를 시도합니다..."
        sudo apt-get install -y python3-pyqt6 2>/dev/null || {
            fail "PySide6/PyQt6를 설치할 수 없습니다. Qt6 관련 패키지를 수동으로 설치하세요."
        }
        warn "PyQt6가 설치되었습니다. PySide6 import는 shim이 필요할 수 있습니다."
    }
fi

# OpenCV — Jetson 시스템 opencv 사용 (CUDA 지원)
if $PYTHON_BIN -c "import cv2" 2>/dev/null; then
    CV_VER=$($PYTHON_BIN -c "import cv2; print(cv2.__version__)")
    log "OpenCV: $CV_VER (시스템)"
else
    sudo apt-get install -y python3-opencv || true
    log "OpenCV: apt 설치"
fi

# 기타 시스템 패키지
sudo apt-get install -y \
    python3-pip \
    python3-yaml \
    python3-numpy \
    python3-pandas \
    2>/dev/null || true

log "시스템 패키지 설치 완료"
echo ""

# -----------------------------------------------
# 3. pip 패키지 설치
# -----------------------------------------------
echo "--- [3/6] pip 패키지 설치 ---"

# laspy[lazrs] — lazrs는 Rust 백엔드, aarch64에서 소스빌드 필요할 수 있음
if $PYTHON_BIN -c "import laspy" 2>/dev/null; then
    log "laspy: 이미 설치됨"
else
    echo "laspy[lazrs] 설치 중... (aarch64에서 Rust 빌드 필요, 수 분 소요될 수 있음)"
    
    # Rust가 없으면 설치 (lazrs 빌드에 필요)
    if ! command -v cargo &>/dev/null; then
        warn "Rust toolchain이 없습니다. lazrs 빌드를 위해 설치합니다..."
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
        source "$HOME/.cargo/env"
    fi
    
    $PYTHON_BIN -m pip install --user "laspy[lazrs]>=2.4.0" || {
        warn "lazrs 빌드 실패. laszip 백엔드로 대체합니다..."
        $PYTHON_BIN -m pip install --user "laspy[laszip]>=2.4.0" || {
            $PYTHON_BIN -m pip install --user "laspy>=2.4.0"
            warn "laspy 설치됨 (압축 백엔드 없음 — LAZ 쓰기 시 비압축)"
        }
    }
fi

# pyyaml, pandas (시스템 패키지로 이미 설치했지만 확인)
$PYTHON_BIN -m pip install --user pyyaml 2>/dev/null || true

log "pip 패키지 설치 완료"
echo ""

# -----------------------------------------------
# 4. PySide6 import 확인
# -----------------------------------------------
echo "--- [4/6] PySide6 import 확인 ---"

if $PYTHON_BIN -c "from PySide6.QtWidgets import QApplication" 2>/dev/null; then
    log "PySide6: import 성공"
else
    warn "PySide6 import 실패. PyQt6 shim 생성을 시도합니다..."
    
    # PyQt6 → PySide6 shim (API가 거의 동일)
    if $PYTHON_BIN -c "from PyQt6.QtWidgets import QApplication" 2>/dev/null; then
        SITE_PACKAGES=$($PYTHON_BIN -c "import site; print(site.getusersitepackages())")
        mkdir -p "$SITE_PACKAGES/PySide6"
        
        cat > "$SITE_PACKAGES/PySide6/__init__.py" << 'SHIMEOF'
# PySide6 → PyQt6 compatibility shim
from PyQt6 import *
SHIMEOF
        
        cat > "$SITE_PACKAGES/PySide6/QtWidgets.py" << 'SHIMEOF'
from PyQt6.QtWidgets import *
SHIMEOF
        
        cat > "$SITE_PACKAGES/PySide6/QtCore.py" << 'SHIMEOF'
from PyQt6.QtCore import *
# PySide6 uses Signal/Slot, PyQt6 uses pyqtSignal/pyqtSlot
Signal = pyqtSignal
Slot = pyqtSlot
SHIMEOF
        
        cat > "$SITE_PACKAGES/PySide6/QtGui.py" << 'SHIMEOF'
from PyQt6.QtGui import *
SHIMEOF
        
        if $PYTHON_BIN -c "from PySide6.QtWidgets import QApplication" 2>/dev/null; then
            log "PyQt6 → PySide6 shim 생성 완료"
        else
            fail "PySide6/PyQt6 모두 사용할 수 없습니다."
        fi
    else
        fail "PySide6와 PyQt6 모두 없습니다. Qt6를 수동으로 설치하세요."
    fi
fi
echo ""

# -----------------------------------------------
# 5. ros2_bag_gui 설치
# -----------------------------------------------
echo "--- [5/6] ros2_bag_gui 설치 ---"

# pyproject.toml이 있는 디렉토리 확인
if [ ! -f "$SCRIPT_DIR/pyproject.toml" ]; then
    fail "pyproject.toml을 찾을 수 없습니다. 이 스크립트는 ros2_bag_gui 루트 디렉토리에 있어야 합니다."
fi

# editable 모드로 설치 (의존성은 이미 수동 설치했으므로 skip)
$PYTHON_BIN -m pip install --user --no-deps -e "$SCRIPT_DIR" || {
    # pip install -e 실패 시 PYTHONPATH로 대체
    warn "pip install -e 실패. PYTHONPATH 방식으로 설정합니다."
    
    SITE_PACKAGES=$($PYTHON_BIN -c "import site; print(site.getusersitepackages())")
    echo "$SCRIPT_DIR/src" > "$SITE_PACKAGES/ros2_bag_gui.pth"
    log "PYTHONPATH 설정 완료: $SCRIPT_DIR/src"
}

# import 확인
$PYTHON_BIN -c "from ros2_bag_gui.main_window import MainWindow; print('import OK')" || {
    fail "ros2_bag_gui import 실패. 설치를 확인하세요."
}

log "ros2_bag_gui 설치 완료"
echo ""

# -----------------------------------------------
# 6. 런치 스크립트 생성
# -----------------------------------------------
echo "--- [6/6] 런치 스크립트 생성 ---"

LAUNCH_SCRIPT="$SCRIPT_DIR/run_gui.sh"
cat > "$LAUNCH_SCRIPT" << 'LAUNCHEOF'
#!/bin/bash
# ROS2 Bag GUI 실행 스크립트

# ROS2 환경 로드
if [ -f /opt/ros/humble/setup.bash ]; then
    source /opt/ros/humble/setup.bash
fi

# 워크스페이스가 있으면 로드 (ouster_ros, zed_ros2_wrapper 등)
if [ -f "$HOME/ros2_ws/install/setup.bash" ]; then
    source "$HOME/ros2_ws/install/setup.bash"
fi

# GUI 실행
python3 -m ros2_bag_gui "$@"
LAUNCHEOF

chmod +x "$LAUNCH_SCRIPT"
log "런치 스크립트 생성: $LAUNCH_SCRIPT"

echo ""
echo "============================================="
echo " 설치 완료!"
echo "============================================="
echo ""
echo " 실행 방법:"
echo "   $LAUNCH_SCRIPT"
echo ""
echo " 또는 수동으로:"
echo "   source /opt/ros/humble/setup.bash"
echo "   python3 -m ros2_bag_gui"
echo ""

if [ "$ZED_OK" = false ]; then
    echo " [참고] ZED SDK가 감지되지 않았습니다."
    echo "        SVO2 녹화/추출 기능은 비활성화됩니다."
    echo "        Camera 모드에서 'Bag에 포함' 만 사용 가능합니다."
    echo ""
fi

echo " 문제 발생 시:"
echo "   python3 -c 'from PySide6.QtWidgets import QApplication'  # Qt 확인"
echo "   python3 -c 'import rosbag2_py'                           # ROS2 확인"
echo "   python3 -c 'import laspy'                                 # LAZ 확인"
echo "   python3 -c 'import pyzed.sl'                              # ZED 확인"
echo ""
