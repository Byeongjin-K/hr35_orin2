#!/bin/bash

# ZED 카메라 원본 이미지 녹화 스크립트 (압축 완전 제거)
# - 이미지 토픽: 원본 (/image_raw_color, 압축 토픽 아님)
# - 파일 압축: 없음 (rosbag 파일도 압축 안함)

# 저장 경로 설정
BASE_DIR="/home/kimm/data"
DATE_DIR=$(date +"%Y%m%d")
TIME_STAMP=$(date +"%H%M%S")
OUTPUT_DIR="${BASE_DIR}/"rosbag2"_${DATE_DIR}_${TIME_STAMP}"


echo "=========================================="
echo "ZED 원본 이미지 녹화 시작 (압축 없음)"
echo "=========================================="
echo "저장 경로: ${OUTPUT_DIR}"
echo ""
echo "📹 녹화 토픽:"
echo "  - /zedx_boom/zedx_boom_node/rgb_raw/image_raw_color"
echo "  - /zedx_boom/zedx_boom_node/left_raw/image_raw_color"
echo "  - /zedx_boom/zedx_boom_node/right_raw/image_raw_color"
echo "  - camera_info 토픽들"
echo "  - IMU 데이터"
echo ""
echo "⚠️  주의사항:"
echo "  - 원본 이미지는 용량이 매우 큽니다 (~3.18 MB/s per topic)"
echo "  - 3개 토픽 = 약 20 MB/s, 시간당 72 GB"
echo "  - 디스크 공간을 충분히 확보하세요!"
echo ""
echo "중지하려면 Ctrl+C를 누르세요"
echo "=========================================="
echo ""

ros2 bag record \
  /zedx_boom/zedx_boom_node/rgb_raw/image_raw_color \
  /zedx_boom/zedx_boom_node/rgb_raw/camera_info \
  /zedx_boom/zedx_boom_node/left_raw/image_raw_color \
  /zedx_boom/zedx_boom_node/left_raw/camera_info \
  /zedx_boom/zedx_boom_node/right_raw/image_raw_color \
  /zedx_boom/zedx_boom_node/right_raw/camera_info \
  /zedx_boom/zedx_boom_node/imu/data \
  --max-bag-size 5368709120 \
  -o "${OUTPUT_DIR}"
  # 압축 옵션 완전 제거 (원본 그대로 저장)
  # 최대 파일 크기: 5GB (금방 차므로 자주 확인 필요)


