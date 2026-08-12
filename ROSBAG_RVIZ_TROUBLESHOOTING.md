# rosbag 녹화 중 rviz2에서 ZED 카메라 영상이 안 나오는 문제 해결

## 🔍 문제 원인

rosbag 녹화 중 rviz2에서 영상이 안 나오는 주요 원인:

1. **높은 대역폭 사용**: 원본 이미지 토픽이 **3.18 MB/s** (메시지당 2.3MB)
2. **여러 토픽 동시 녹화**: 6개 이미지 토픽 = 총 **~20MB/s** 처리
3. **시스템 리소스 부족**: CPU/메모리/디스크 I/O 포화
4. **rviz2 구독 실패**: 리소스 부족으로 구독 연결 실패

## ✅ 해결 방법 (3가지)

### **방법 1: rviz2에서 압축 토픽 사용 (가장 간단) ⭐**

rviz2를 열고:
1. 왼쪽 패널 **Add** 버튼 클릭
2. **By topic** 탭 선택
3. 다음 토픽 중 하나 선택:
   ```
   /zedx_boom/zedx_boom_node/left_raw/image_raw_color/compressed
   또는
   /zedx_boom/zedx_boom_node/rgb_raw/image_raw_color/compressed
   ```
4. **Transport Hint**를 `compressed`로 설정 (자동으로 설정될 수도 있음)

**효과**: 대역폭 **70% 절감** (3.18 MB/s → 1 MB/s)

---

### **방법 2: rosbag 녹화를 압축 토픽으로 변경 (권장) ⭐⭐**

현재 rosbag 프로세스를 중지하고 (Ctrl+C), 다음 스크립트 실행:

```bash
cd /home/kimm/robot_ws
./scripts/record_zed_compressed.sh
```

또는 직접 명령어 실행:

```bash
ros2 bag record \
  /zedx_boom/zedx_boom_node/rgb_raw/image_raw_color/compressed \
  /zedx_boom/zedx_boom_node/rgb_raw/camera_info \
  /zedx_boom/zedx_boom_node/left_raw/image_raw_color/compressed \
  /zedx_boom/zedx_boom_node/left_raw/camera_info \
  /zedx_boom/zedx_boom_node/right_raw/image_raw_color/compressed \
  /zedx_boom/zedx_boom_node/right_raw/camera_info \
  /zedx_boom/zedx_boom_node/imu/data \
  --compression-mode file \
  --compression-format zstd \
  --max-cache-size 100000000 \
  --max-bag-size 3073741824
```

**장점**:
- rosbag 파일 크기도 70% 감소
- 시스템 부하 대폭 감소
- rviz2 시각화 문제 해결

**단점**:
- 재생 시 압축 해제 필요 (약간의 CPU 사용)

---

### **방법 3: 녹화 fps 감소 (임시 방편)**

ZED 카메라 파라미터 수정:

**파일**: `/home/kimm/robot_ws/src/hr35_bringup/config/zedx_boom_params.yaml`

```yaml
general:
  pub_frame_rate: 10.0  # 현재값. 낮추면 대역폭이 비례해 줄어듦
```

**효과**: 대역폭 감소하지만 영상 끊김

---

## 🔧 현재 시스템 상태

### 발행 중인 토픽들:
```bash
# 원본 이미지 (고대역폭)
/zedx_boom/zedx_boom_node/left_raw/image_raw_color          # 3.18 MB/s
/zedx_boom/zedx_boom_node/rgb_raw/image_raw_color           # 3.18 MB/s
/zedx_boom/zedx_boom_node/right_raw/image_raw_color         # 3.18 MB/s

# 압축 이미지 (저대역폭) ⭐
/zedx_boom/zedx_boom_node/left_raw/image_raw_color/compressed   # 1.0 MB/s
/zedx_boom/zedx_boom_node/rgb_raw/image_raw_color/compressed    # 1.0 MB/s
/zedx_boom/zedx_boom_node/right_raw/image_raw_color/compressed  # 1.0 MB/s

# Rectified 이미지
/zedx_boom/zedx_boom_node/left/image_rect_color
/zedx_boom/zedx_boom_node/rgb/image_rect_color
```

### 현재 rosbag 명령어:
```bash
# 확인 방법
ps aux | grep "ros2 bag" | grep -v grep
```

---

## 🎯 권장 사항

**최선의 방법**: **방법 1 + 방법 2 조합**

1. rosbag을 **압축 토픽**으로 녹화 (방법 2)
2. rviz2도 **압축 토픽**으로 시각화 (방법 1)
3. **max-cache-size**를 200MB → 100MB로 감소 (이미 적용됨)

이렇게 하면:
- ✅ 디스크 공간 70% 절약
- ✅ 시스템 부하 대폭 감소
- ✅ rviz2 실시간 시각화 가능
- ✅ 영상 품질 거의 동일 (JPEG 압축)

---

## 🔍 문제 진단 명령어

```bash
# 1. 토픽 대역폭 확인
ros2 topic bw /zedx_boom/zedx_boom_node/left_raw/image_raw_color

# 2. 압축 토픽 대역폭 확인
ros2 topic bw /zedx_boom/zedx_boom_node/left_raw/image_raw_color/compressed

# 3. 토픽 발행 확인
ros2 topic list | grep zed

# 4. 구독자 수 확인 (0이면 문제)
ros2 topic info -v /zedx_boom/zedx_boom_node/left_raw/image_raw_color

# 5. 시스템 리소스 확인
htop  # CPU/메모리 사용량
iostat -x 1  # 디스크 I/O
```

---

## 📝 참고 사항

- **image_raw_color**: 원본 미보정 컬러 이미지
- **image_rect_color**: Rectified(보정된) 컬러 이미지
- **/compressed**: JPEG 압축된 이미지 (70% 크기 감소)
- **QoS RELIABLE**: 데이터 손실 없이 전송 (높은 대역폭 필요)

---

## 🚨 긴급 대응

rosbag 녹화 중 시스템이 멈추거나 느려지면:

1. **즉시 rosbag 중지**: Ctrl+C
2. **rviz2 종료**: 리소스 확보
3. **압축 토픽으로 재시작**: 위 방법 2 사용
4. **필요 시 fps 감소**: zedx_boom_params.yaml 수정

---

## 🎬 rosbag 재생 시 압축 이미지 처리

### **Q: 압축된 이미지는 rosbag play 할 때 별도 처리가 필요한가요?**

**A: 대부분의 경우 필요 없습니다!** ⭐

#### **시나리오 1: rviz2로 시각화 (일반적인 경우)**

```bash
# 1. rosbag 재생
ros2 bag play your_bag_file

# 2. rviz2 실행 및 압축 토픽 선택
rviz2
# Add → Image → Topic: /zedx_boom/.../compressed
```

**✅ 별도 처리 불필요!** rviz2가 `image_transport` 플러그인으로 자동 압축 해제합니다.

---

#### **시나리오 2: 압축 해제된 원본 토픽 필요 시 (특수한 경우)**

만약 다른 노드가 **압축되지 않은 `sensor_msgs/Image`** 타입을 요구한다면:

```bash
# 터미널 1: rosbag 재생
ros2 bag play your_bag_file

# 터미널 2: 압축 해제 스크립트 실행
cd /home/kimm/robot_ws
./scripts/decompress_images.sh

# 터미널 3: 압축 해제된 토픽 사용
ros2 topic list | grep decompressed
# 출력:
#   /zedx_boom/.../left_raw/image_raw_color_decompressed
#   /zedx_boom/.../rgb_raw/image_raw_color_decompressed
#   /zedx_boom/.../right_raw/image_raw_color_decompressed
```

**수동 압축 해제 (단일 토픽):**

```bash
ros2 run image_transport republish compressed raw \
  --ros-args \
  --remap in/compressed:=/zedx_boom/zedx_boom_node/left_raw/image_raw_color/compressed \
  --remap out:=/my_decompressed_topic
```

---

#### **압축 vs 원본 비교**

| 항목 | 압축 토픽 (`/compressed`) | 원본 토픽 (`sensor_msgs/Image`) |
|------|---------------------------|----------------------------------|
| **메시지 크기** | 318 KB | 2.3 MB |
| **대역폭** | 1 MB/s | 3.18 MB/s |
| **rviz2 지원** | ✅ 자동 지원 | ✅ 기본 지원 |
| **이미지 처리 노드** | ⚠️ 압축 해제 필요 (일부) | ✅ 직접 사용 가능 |
| **재생 시 CPU** | 약간 높음 (해제) | 낮음 |

---

#### **요약**

1. **rviz2만 사용**: 별도 처리 불필요 ✅
2. **OpenCV/이미지 처리**: `republish` 필요 (위 스크립트 사용)
3. **저장 공간**: 압축 토픽이 70% 절약 ✅
4. **품질**: JPEG 압축이지만 시각적 차이 거의 없음 ✅

**권장**: 대부분의 경우 압축 토픽으로 저장하고, 필요 시에만 `republish` 사용!

---

**작성일**: 2025-11-11  
**문제 해결 시간**: 즉시 (방법 1) ~ 5분 (방법 2)  
**효과**: 대역폭 70% 절감, rviz2 정상 작동

