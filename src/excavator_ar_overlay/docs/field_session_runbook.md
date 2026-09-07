# 현장 세션 런북 — 카메라 외부 파라미터(A) 캡처와 풀이

목적 하나: `T_camera ← gm_swing_axis` 를 **0.72° / 0.075 m** 안으로 확정한다. 이 값이
없으면 오버레이 기하는 전부 미검증이고 의뢰서 §8 의 1·2·3 을 판정할 수 없다.

현장 소요는 캡처 15분 + 그 자리에서 푸는 데 20분이다. 풀이까지 현장에서 끝내야
한다 — 실패하면 다시 부르기 전에 다시 찍을 수 있어야 하기 때문이다.

---

## 0. 왜 이 방식인가 (되풀이하지 말 것)

이미 실패한 경로들이다. 다시 시도하지 않는다.

| 시도 | 결과 | 원인 |
|---|---|---|
| 자동 엣지 정합 4종 (합/평균/고정정규화/HSV) | 매번 다른 답, 전부 검증 실패 | 목적함수가 양방향으로 게임 가능 |
| 펜스 기둥 대응점 | 불가 | 잔디가 밑동을 가려 점이 아니라 선만 나옴 |
| 버킷 끝단 대응점 | 불가 (PnP 축퇴) | 붐·암·버킷이 전부 시상면 안에서만 움직이고, 스윙하면 카메라가 같이 돌아 이미지 안에서 버킷이 안 움직임 |

남은 방법은 하나다: **기계와 독립적으로 움직이는 타깃을 여러 위치에 놓고 인터벌
캡처로 찍는다.** 사람은 가동 기계 근처라 안전상 배제했다. 물체를 쓴다.

---

## 1. 준비물

- 이미지·클라우드 양쪽에서 명확히 식별되는 타깃 **1개**
  - 조건: 높이 0.3 m 이상(라이다 점이 지면과 분리됨), 폭 0.3 m 이상, 색이 흙·잔디와 대비.
  - 후보: 콘, 밝은 합판/양동이, 각목에 흰 테이프. 없으면 버킷으로 만든 작은 흙더미도 가능하나
    윤곽이 흐려 정밀도가 떨어진다.
- 줄자(타깃 위치 기록용, 선택).
- 노트북에서 이 저장소 접근 가능할 것.

## 2. 사전 점검 (기계 앞에서, 5분)

```bash
source /opt/ros/humble/setup.bash
source ~/robot_ws/install/setup.bash
ros2 topic hz /lidar_boom/points            # 10 Hz 부근
ros2 topic hz /zedx_cabin/zedx_cabin_node/rgb/image_rect_color/compressed
ros2 run tf2_ros tf2_echo map gm_swing_axis # 값이 나와야 함
df -h ~/data                                 # 한 세션 ~15 MB
```
셋 중 하나라도 비면 캡처는 의미가 없다. 특히 카메라 스트림이 죽으면 캡처 노드는
같은 프레임을 반복 저장하려 하는데, 이제는 노드가 이를 거부하고
`no new image since the last capture (stream stalled?)` 로 경고한다. 이 경고가
반복되면 즉시 중단하고 카메라부터 살린다.

## 3. 캡처 (10~15분)

붐은 **한 자세로 고정**한다(작업 자세, 예: pitch -45°). 붐을 움직이는 것은 B 판정용이었고
이미 끝났다. 이번에 필요한 것은 **타깃의 공간 분포**다.

```bash
source /opt/ros/humble/setup.bash
source ~/robot_ws/install/setup.bash
ros2 run excavator_ar_overlay snapshot_capture_node --ros-args \
  -p capture.mode:=interval \
  -p capture.interval_seconds:=15.0 \
  -p capture.output_dir:=$HOME/data/lidar_cam_calib_$(date +%Y%m%d)
```
노드가 15초마다 한 장씩 찍고, 남은 초를 로그로 카운트다운한다. 카운트다운 동안
타깃을 다음 위치로 옮기고 **화면 밖으로 비켜선다**(사람이 프레임에 들어와도 캡처는
되지만, 대응점 후보가 헷갈린다).

배치 순서 — 깊이와 좌우를 반드시 섞는다. 한 평면에 몰리면 해가 퇴화한다:

| # | 거리(전방 m) | 좌우 | 비고 |
|---|---|---|---|
| 1 | 2.5 | 중앙 | 근거리 |
| 2 | 2.5 | 좌단 | |
| 3 | 2.5 | 우단 | |
| 4 | 4.5 | 중앙 | |
| 5 | 4.5 | 좌단 | |
| 6 | 4.5 | 우단 | |
| 7 | 7.0 | 중앙 | 원거리 |
| 8 | 7.0 | 좌단 | |
| 9 | 7.0 | 우단 | |

"좌단/우단"은 자로 잰 값이 아니라 **카메라 화면의 좌우 끝 부근**이다. 화면을 보며
넣는다. 타깃은 매번 **지면에 놓는다**(높이는 적합된 지면 평면에서 온다).

9장을 다 찍으면 `Ctrl-C`.

## 4. 그 자리에서 검수 (2분)

```bash
python3 - <<'PY'
import glob, json, cv2, numpy as np, os
d = sorted(glob.glob(os.path.expanduser('~/data/lidar_cam_calib_*/')))[-1]
for m in sorted(glob.glob(d+'*_meta.json')):
    j = json.load(open(m)); img = cv2.imread(m.replace('_meta.json','_image.jpg'))
    print(os.path.basename(m), j['cloud_points'], 'pts', img.shape,
          'mean', round(float(img.mean()),1))
PY
```
- `cloud_points` 가 3만 부근이어야 한다. 급감하면 라이다가 죽은 것.
- `mean` 이 30~220 밖이면 노출 불량 — 노드도 같은 기준으로 경고한다. 해당 위치는 다시 찍는다.
- 이미지 해시가 서로 달라야 한다(같으면 스트림 정지 — 노드가 이미 거부했어야 함).

## 5. 대응점 만들기 (노트북, 15분)

각 캡처마다 **타깃 한 점**이 대응점 하나가 된다. 9장이면 9점이고, 6점이면 풀 수 있다.

**픽셀(2D)** — 격자 오버레이를 띄우고 타깃의 **접지점**(타깃이 지면과 만나는 지점)의
좌표를 읽는다:
```bash
python3 src/excavator_ar_overlay/scripts/solve_extrinsic_pnp.py --grid shot00
# -> ..._grid.png 를 열어 100 px 격자 위에서 좌표를 읽는다
```

**3D** — 같은 캡처의 클라우드에서 타깃 클러스터를 잡는다:
```bash
python3 - <<'PY'
import numpy as np, json
stem = '/home/kimm/data/lidar_cam_calib_YYYYMMDD/shot00_boom-046.0'
pts = np.load(stem+'_cloud.npy')          # 클라우드는 헤더 프레임(=gm_os_lidar 체인)
# 대략적인 관심 영역으로 자르고(전방 x, 좌우 y), 지면 위로 솟은 점만 남긴다
sel = pts[(pts[:,0]>1.5)&(pts[:,0]<9)&(abs(pts[:,1])<4)]
above = sel[sel[:,2] > np.percentile(sel[:,2], 20) + 0.25]
print('cluster centroid:', above.mean(axis=0), 'n=', len(above))
PY
```
접지점의 z 는 세션에서 적합한 지면 평면 값(2026-08-18 기준 `z = 0.155 m`)을 쓴다.
클러스터가 여러 개면 예상 위치에 가장 가까운 것을 고른다.

> 클라우드는 라이다 프레임 기준이다. 대응점의 3D 는 **`gm_swing_axis` 기준**이어야
> 하므로, meta.json 의 `transforms` 에 얼려둔 `map→gm_os_lidar` 와 `map→gm_swing_axis`
> 로 변환해서 넣는다. 이 변환은 캡처 시각에 고정돼 있으므로 오프라인으로 정확히 된다.

`pairs.json`:
```json
{"points": [
  {"px": [812, 517], "xyz": [2.51, -0.03, 0.155], "note": "shot00 target base"},
  {"px": [304, 498], "xyz": [2.48,  1.92, 0.155], "note": "shot01 target base"}
]}
```

## 6. 풀이와 합격 판정

```bash
python3 src/excavator_ar_overlay/scripts/solve_extrinsic_pnp.py \
  --pairs pairs.json --pose shot00
```
합격선 — **네 개 전부** 만족해야 한다:

1. `reprojection err: mean` < 1.0 px
2. `within the reported install envelope: True` (캐빈 지붕: x 0~1.6, y -0.3~1.2, z 2~3 m)
3. `pitch below horizon` 이 작업면을 내려다보는 값(대략 15~40°)
4. `leave-one-out ... -> PASS` (worst ≤ 0.72° / 0.075 m)

하나라도 어긋나면 **대응점이 틀린 것이지 도구가 틀린 것이 아니다**. 잘못 읽힌 점은
per-point 재투영 오차에서 가장 큰 값으로 드러난다. 그 점을 지우고 다시 푼다.
화면 밖 좌표는 도구가 아예 거부한다(`... fall outside the 1280x800 image`).

## 7. 확정 후 (현장에서 바로)

```bash
# 1) 파라미터 반영 (재빌드 불필요)
ros2 param set /lidar_projection_node extrinsic.xyz "[x, y, z]"
ros2 param set /lidar_projection_node extrinsic.rpy "[r, p, yaw]"
# 2) 눈으로 확인: 오버레이의 깊이 불연속이 실제 물체 윤곽에 걸치는가 (의뢰서 §8-1)
ros2 run rqt_image_view rqt_image_view /excavator/perception/dig_overlay/compressed
```
맞으면 `config/lidar_projection_params.yaml` 의 `extrinsic.xyz/rpy` 에 써 넣고 커밋한다.
최종적으로는 `static_transform_publisher` 나 URDF 로 옮기고
`extrinsic.publish_static_tf: false` 로 바꾼다.

## 8. 같은 방문에 묶어서 할 것 (A 가 끝난 뒤)

- **C-4 (A 무관, 언제든 가능)**: AI 한 사이클을 돌리며 dig 중 30초 침묵을 견디는지,
  phase=idle 에서 셀이 사라지는지 관찰. `/ai_status/action` 과 `/task_info` 가
  살아 있어야 하므로 hr35 스택 기동이 선행된다.
- **D (파라미터 1줄)**:
  `ros2 param set /task_config_gui_node ai_camera_image_topic /excavator/perception/dig_overlay/compressed`
  화면이 안 바뀌면 GUI 설정 파일을 고치고 재시작. 오버레이 입력이 비면
  `topics.image_in` 을 `rgb/` 대신 `left/` 계열로.
- **C-2 / C-3**: 굴착 전/후 영상 비교, `/ai_coordinate_diagnostics` 의
  `commanded_physical` 과 오버레이 셀 물리좌표 대조.

## 9. 실패 시 대안

- 타깃 대응점이 6점 미만으로 유효하면: 같은 자리에서 타깃을 더 촘촘히(1.5 m 간격) 다시 배치.
- 그래도 안 되면 재귀반사 테이프 + 라이다 반사강도 채널로 자동 검출하는 경로가 남아 있다.
  현재 캡처는 XYZ 만 저장하므로 그 경우 `pointcloud.extract_xyz` 를 반사강도까지
  저장하도록 넓혀야 한다 (코드 작업, 현장 불필요).
