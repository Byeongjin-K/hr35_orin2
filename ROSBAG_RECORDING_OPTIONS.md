# ZED 카메라 rosbag 녹화 옵션 비교

## 🎯 3가지 녹화 방법

### **옵션 1: 원본 이미지 + 파일 압축 (현재 실행 중)** ⭐

**스크립트**: 현재 실행 중인 명령어

```bash
ros2 bag record \
  /zedx_boom/zedx_boom_node/rgb_raw/image_raw_color \
  /zedx_boom/zedx_boom_node/left_raw/image_raw_color \
  /zedx_boom/zedx_boom_node/right_raw/image_raw_color \
  ... \
  --compression-mode file \
  --compression-format zstd
```

**특징**:
- ✅ 이미지 토픽: **원본** (`image_raw_color`)
- ✅ 파일 압축: **있음** (zstd로 rosbag 파일 자체를 압축)
- 📊 디스크 사용량: **중간** (~10-15 GB/시간)
- 🎬 재생 시: 자동 압축 해제, 별도 처리 불필요

---

### **옵션 2: 원본 이미지 + 압축 없음 (완전 원본)** 💾

**스크립트**: `/home/kimm/robot_ws/scripts/record_zed_raw_no_compression.sh`

```bash
./scripts/record_zed_raw_no_compression.sh
```

**특징**:
- ✅ 이미지 토픽: **원본** (`image_raw_color`)
- ❌ 파일 압축: **없음** (압축 옵션 완전 제거)
- 📊 디스크 사용량: **매우 큼** (~72 GB/시간)
- 🎬 재생 시: 즉시 재생 가능
- ⚠️ 주의: 디스크 공간 빠르게 소모

---

### **옵션 3: 압축 이미지 + 파일 압축 (최소 용량)** 💰

**스크립트**: `/home/kimm/robot_ws/scripts/record_zed_compressed.sh`

```bash
./scripts/record_zed_compressed.sh
```

**특징**:
- ✅ 이미지 토픽: **압축** (`image_raw_color/compressed`)
- ✅ 파일 압축: **있음** (zstd)
- 📊 디스크 사용량: **최소** (~3-5 GB/시간)
- 🎬 재생 시: rviz2가 자동 압축 해제
- 💡 품질: JPEG 압축이지만 시각적 차이 거의 없음

---

## 📊 상세 비교표

| 항목 | 옵션 1: 원본+파일압축 | 옵션 2: 완전 원본 | 옵션 3: 압축+파일압축 |
|------|---------------------|------------------|---------------------|
| **이미지 토픽** | `image_raw_color` | `image_raw_color` | `image_raw_color/compressed` |
| **메시지 크기** | 2.3 MB | 2.3 MB | 318 KB |
| **파일 압축** | zstd ✅ | 없음 ❌ | zstd ✅ |
| **디스크 사용** | ~12 GB/시간 | ~72 GB/시간 | ~4 GB/시간 |
| **녹화 시 CPU** | 중간 (압축) | 낮음 | 낮음 |
| **재생 시 CPU** | 중간 (해제) | 낮음 | 중간 (해제) |
| **이미지 품질** | 완벽 (무손실) | 완벽 (무손실) | 매우 좋음 (JPEG) |
| **rviz2 지원** | ✅ 자동 | ✅ 자동 | ✅ 자동 |
| **OpenCV 처리** | ✅ 직접 사용 | ✅ 직접 사용 | ⚠️ republish 필요 |

---

## 🎯 사용 시나리오별 권장

### **시나리오 1: 나중에 이미지 처리/분석 (컴퓨터 비전)** 
→ **옵션 1 권장** ⭐
- 원본 이미지 필요
- 파일 압축으로 디스크 절약
- OpenCV 등에서 바로 사용 가능

### **시나리오 2: 최고 품질 보존 (연구/논문)**
→ **옵션 2 권장** 💾
- 완전한 원본 데이터
- 압축 아티팩트 0%
- 디스크 공간 충분할 때만

### **시나리오 3: 장시간 녹화/시각화만 필요**
→ **옵션 3 권장** 💰
- 디스크 공간 최소화
- rviz2 시각화는 완벽
- 컴퓨터 비전 처리 시 republish 필요

---

## 🔧 현재 상태 확인

```bash
# 현재 녹화 중인 명령어 확인
ps aux | grep "ros2 bag record" | grep -v grep

# 녹화 중인 토픽 확인
ros2 topic list | grep zedx_boom | grep image

# 토픽 타입 확인
ros2 topic info /zedx_boom/zedx_boom_node/left_raw/image_raw_color

# 대역폭 확인
ros2 topic bw /zedx_boom/zedx_boom_node/left_raw/image_raw_color
```

---

## 💡 이미지 토픽 vs 파일 압축 이해하기

### **1️⃣ 이미지 토픽 압축 (토픽 이름에 `/compressed`)**

```
원본 토픽:    /zedx_boom/.../image_raw_color         (sensor_msgs/Image, 2.3MB)
압축 토픽:    /zedx_boom/.../image_raw_color/compressed  (sensor_msgs/CompressedImage, 318KB)
```

- **압축 방식**: JPEG/PNG (이미지 압축)
- **언제**: 토픽 발행 시점
- **영향**: 메시지 크기, 네트워크 대역폭, 품질

### **2️⃣ rosbag 파일 압축 (`--compression-mode file`)**

```
압축 없음:    my_bag_0.db3 (72 GB/시간)
파일 압축:    my_bag_0.db3 (12 GB/시간, zstd 압축됨)
```

- **압축 방식**: zstd/lz4 (파일 압축)
- **언제**: 디스크 저장 시점
- **영향**: 파일 크기, 저장/읽기 속도

---

## 🚀 빠른 전환 가이드

### **현재 녹화 중단하고 다른 옵션으로 전환**

1. **현재 rosbag 중지**: Ctrl+C

2. **원하는 옵션 실행**:

```bash
cd /home/kimm/robot_ws

# 옵션 1: 원본 + 파일압축 (균형 잡힌 선택)
ros2 bag record /zedx_boom/.../image_raw_color ... --compression-mode file

# 옵션 2: 완전 원본 (최고 품질)
./scripts/record_zed_raw_no_compression.sh

# 옵션 3: 압축 토픽 (최소 용량)
./scripts/record_zed_compressed.sh
```

---

## 📈 디스크 공간 계산

```
1시간 녹화 예상 용량:

옵션 1 (원본+파일압축):
  20 MB/s × 3600초 × 0.2 (압축률) = ~14.4 GB/시간

옵션 2 (완전 원본):
  20 MB/s × 3600초 = 72 GB/시간

옵션 3 (압축+파일압축):
  3 MB/s × 3600초 × 0.2 (압축률) = ~2.2 GB/시간
```

---

## ⚠️ 중요 참고사항

### **원본 이미지 토픽 (`image_raw_color`)**
- ✅ 장점: 완벽한 품질, 모든 처리 가능
- ❌ 단점: 용량 큼, 네트워크/디스크 부하 높음

### **압축 이미지 토픽 (`/compressed`)**
- ✅ 장점: 용량 작음, 부하 낮음
- ❌ 단점: JPEG 아티팩트 (미미함), 일부 처리에서 republish 필요

### **파일 압축 (`--compression-mode file`)**
- ✅ 장점: 디스크 공간 절약, 재생 시 자동 해제
- ❌ 단점: 녹화/재생 시 약간의 CPU 사용

---

## 🎬 권장 조합

**일반적인 경우**: **옵션 1** (원본 이미지 + 파일 압축) ⭐
- 품질과 용량의 균형
- 대부분의 사용 케이스 커버
- 현재 실행 중인 설정!

**특별한 경우**:
- 연구/논문: 옵션 2
- 장시간 모니터링: 옵션 3

---

**작성일**: 2025-11-11  
**현재 실행 중**: 옵션 1 (원본 이미지 + 파일 압축)








