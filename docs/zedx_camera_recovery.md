# ZED X 카메라가 안 열릴 때 (`CAMERA STREAM FAILED TO START`)

대상: exca-orin-2 (Jetson Orin, JetPack 6 / L4T 5.15.148-tegra, ZED SDK 5.0.2)
카메라: ZED X 2대 — SN45233238 (i2c-9, boom), SN49749405 (i2c-10, cabin)

## 1. 30초 판정

```bash
bash ~/robot_ws/scripts/zedx_health.sh
```

| VERDICT | exit | 뜻 | 조치 |
|---|---|---|---|
| `HEALTHY` | 0 | 스택 정상 | 조치 없음. 그래도 안 열리면 다른 프로세스가 점유 중(출력의 `camera clients` 확인) |
| `RECOVERABLE` | 1 | 캡처 세션이 클라이언트보다 오래 살아남음 | `sudo systemctl restart nvargus-daemon` → 안 되면 `zed_x_daemon` |
| `REBOOT_REQUIRED` | 2 | `sl_zedx` 모듈 use-count 파손 | `sudo bash ~/robot_ws/scripts/zedx_recover.sh` (7장). 그래도 안 되면 재부팅 |

## 2. 복구 사다리 (위에서부터, 열리면 즉시 중단)

1. **클라이언트 정리** — `pgrep -af component_container`
   살아 있으면 `pkill -INT -f component_container_isolated` 후 종료 확인. (죽이지 말고 얌전히 끝내기)
2. **argus 재시작** — `sudo systemctl restart nvargus-daemon`
   argus 안에 남은 캡처 세션을 날린다. 대부분 여기서 해결.
3. **드라이버 재로드** — `sudo systemctl restart zed_x_daemon`
   **반드시 실제로 되었는지 확인할 것:**
   ```bash
   journalctl -u zed_x_daemon -n 20 --no-pager | grep -E 'rmmod|insmod'
   ```
   `is in use` 또는 `File exists` 가 보이면 **재로드는 일어나지 않았다**. 4번으로.
4. **재부팅** — `sudo reboot`

> `zed_x_daemon` 은 내부 `rmmod`/`insmod` 가 전부 실패해도 로그에 `ZED-X Driver removed` /
> `ZED-X Driver loaded` 를 그대로 출력한다. 이 문구는 성공의 증거가 아니다.

## 3. 왜 재부팅이어야 하는가 (2026-09-08 사례 분석)

증상: `zedx_cabin` 노드가 `Error opening camera: CAMERA STREAM FAILED TO START` 로 재시도 반복.
물리 연결은 정상 — 커널이 부팅 시 두 카메라를 모두 인식했다.

```
sl_max96712 9-0029: GMSL port 2 / port 3 에 zedx 감지, pipes_setup: camera pipeline operational
zedx 9-0020 -> S/N 45233238,  zedx 10-0020 -> S/N 49749405
/dev/video0..3 정상 생성, 전부 open 가능 (EBUSY 아님)
ZED SDK 가 두 시리얼을 모두 열거 -> I2C/MCU 통신 정상
```

고장은 그보다 위, **argus 캡처 경로**에서 났다.

1. 스트리밍 중이던 `component_container` 가 정리 없이 죽었다.
   `nvargus-daemon`: `SCF: Error InvalidState: 5 buffers still pending during EGLStreamProducer destruction`
2. argus 는 그 센서를 계속 "할당됨"으로 취급한다.
   `(Argus) Error AlreadyAllocated: Device 0 (of 1) is in use` (`CameraProviderImpl.cpp:286`)
3. 이 상태에서 `open()` 을 하면 21초 후 `[ZED] Cannot initialize the camera` 와 함께
   **nvargus-daemon 자체가 죽는다** (`Failed socket read: Connection reset by peer`, systemd 가 재기동).
   클라이언트는 `acquireFrame` `BadParameter` 를 수천 줄 뱉으며 반환하지 않고 멈춘다.
   → 이때 정상이던 다른 카메라도 같이 못 연다. (한 대만 실패 = 세션 누수 / 두 대 다 실패 = 스택 고장)
4. 실패한 `open()` 이 죽을 때 v4l2 release 경로에서 커널 refcount 가 어긋난다.
   ```
   zedx 10-0020: Error turning off streaming
   WARNING: CPU: 2 PID: 32025 at kernel/module.c:1095 module_put+0x18c/0x1b0
     module_put <- tegracam_v4l2subdev_register <- tegra_channel_set_stream
                <- _vb2_fop_release <- __fput <- do_exit
   ```
   결과: `cat /sys/module/sl_zedx/refcnt` → `-1`.
5. refcount 가 음수가 되면 `rmmod` 는 영원히 "in use" 로 실패한다.
   `zed_x_daemon` 재시작이 하는 일은 rmmod + insmod 이므로 **조용히 무효화**된다:
   ```
   rmmod sl_max9295  -> ERROR: Module sl_max9295 is in use by: sl_zedx
   insmod sl_zedx.ko -> ERROR: could not insert ...: File exists
   ```
   커널에 `CONFIG_MODULE_FORCE_UNLOAD` 가 꺼져 있어 `rmmod -f` 도 없다.
   → 모듈 상태를 되돌리는 유일한 수단이 재부팅이다.

주의: 4~5번(refcount 언더플로)은 3번 상태에서 `open()` 을 재시도할 때마다 누적된다.
관측된 순서상 **최초 고장의 원인이 아니라 복구 경로를 막는 악화 요인**이다.
그러므로 **안 열릴 때 계속 재시도하지 말고 위 사다리 순서대로** 진행할 것.

## 4. 재발 방지

- **ZED 노드는 Ctrl-C 한 번만.** 두 번 이상 누르거나 `kill -9` 로 끊으면 argus 세션과
  커널 refcount가 어긋난다. `[INFO] process has finished cleanly` 를 확인하고 다음 런치를 띄운다.
- 카메라가 안 열릴 때 **런치를 반복해서 재시도하지 말 것.** 시도마다 상태가 더 나빠진다.
  먼저 `zedx_health.sh` 로 판정한다.
- **journald 영속화**(현재 꺼져 있음 — 재부팅하면 이전 부팅 로그가 사라져 원인 분석이 불가능했다):
  ```bash
  sudo mkdir -p /var/log/journal
  sudo systemd-tmpfiles --create --prefix /var/log/journal
  sudo systemctl kill --kill-who=main -s SIGUSR2 systemd-journald   # 또는 재부팅
  journalctl --list-boots      # 부팅이 2개 이상 보이면 성공
  ```

## 5. 확인 명령 모음

```bash
# 모듈 상태 (음수면 재부팅)
cat /sys/module/sl_zedx/refcnt

# 커널이 카메라를 봤는가
journalctl -k -b 0 | grep -E 'sl_max96712.*(GMSL port|pipeline)|zedx_probe: Serial Number'

# argus 가 죽고 있는가
systemctl show nvargus-daemon -p MainPID -p ActiveEnterTimestamp

# SDK 열거 (ROS 노드가 잡고 있으면 해당 카메라는 NOT AVAILABLE 이 정상)
python3 -c "import pyzed.sl as sl; print([(d.serial_number, str(d.camera_state)) for d in sl.Camera.get_device_list()])"

# 실제 스트림 확인
ros2 topic hz /zedx_cabin/zedx_cabin_node/left/image_rect_color
```

## 6. 확인된 재발 (2026-09-09) — 사다리 2·3단계는 refcnt 음수면 쓸모없다

같은 고장이 하루 만에 재발했다. `zedx_health.sh` 가 30초 만에 `REBOOT_REQUIRED` 를 냈고,
그 판정이 맞다는 것을 사다리를 끝까지 돌려서 증거로 확인했다.

- 2단계 `systemctl restart nvargus-daemon` → 재시작 성공, device list 는 두 카메라 모두 `AVAILABLE`
  로 보였지만 `open()` 은 **반환하지 않고 멈춤**(probe `EXIT=124` = timeout kill).
- 3단계 `systemctl restart zed_x_daemon` → 로그는 `ZED-X Driver loaded` 라고 했지만 실제로는:
  ```
  rmmod sl_max9295  -> ERROR: Module sl_max9295 is in use by: sl_zedx
  insmod sl_zedx.ko -> ERROR: could not insert ...: File exists
  ```
  `open()` 역시 다시 행 (`EXIT=124`).

**따라서 `cat /sys/module/sl_zedx/refcnt` 가 음수면 2·3단계는 건너뛴다.** 이때 쓰는 것이 7장의 `zedx_recover.sh` 다(2026-09-09 이전에는 여기서 재부팅밖에 없었다).
시도할 때마다 open 이 90초씩 멈추고 언더플로만 더 쌓인다(이번에 8회 추가됨).

### 망가지는 순간은 "띄울 때"가 아니라 "내릴 때"다

이번 부팅의 커널 로그 순서:

```
09:59:46  nvargus 세션 시작 (카메라 정상 동작)
10:56:04  zedx 10-0028: Error turning off streaming   <- 여기서 teardown 실패
10:57:16  WARNING at kernel/module.c:1095 module_put  <- refcnt = -1 확정
11:52~    이후 모든 런치는 CAMERA STREAM FAILED TO START
```

즉 **정상 동작하던 세션을 종료하는 그 순간** 상태가 깨졌고, 그 뒤의 런치는 전부 실패할 운명이었다.
그러므로:

- ZED 노드를 내린 직후 `bash ~/robot_ws/scripts/zedx_health.sh` 를 한 번 돌린다.
  `HEALTHY` 가 아니면 **다음 런치를 띄우지 말고** 판정에 따른다.
- 내릴 때 Ctrl-C 한 번 → `process has finished cleanly` 확인. 안 끝난다고 **Ctrl-Z 로 백그라운드에
  밀어놓고 새 런치를 띄우지 말 것.** 중지(T) 상태 프로세스는 종료 경로를 실행하지 않으므로
  카메라를 계속 붙잡은 채 남고, 두 번째 런치가 그 위에 겹친다. (2026-09-09 실제 관측:
  pid 230570/230599/230601 이 T 상태로 남은 채 231586 런치가 겹쳐 있었다)
- 사고 로그는 재부팅하면 사라진다. 재부팅 전에 `~/data/zedx_incidents/` 로 덤프해 두거나,
  4장의 journald 영속화를 먼저 적용한다.

## 7. 무재부팅 복구 (2026-09-09 확립)

### 근본 원인 — 소스 코드 위치까지 특정됨

NVIDIA tegracam 의 V4L2 글루는 스트리밍 시작 때 `try_module_get(s_data->owner)` 로 센서 모듈
참조를 잡고, 정지 때 `module_put()` 으로 놓는다. 그런데 센서의 `stop_streaming()` 이 에러를
반환하면 정지 경로가 `error:` 라벨로 떨어지면서 **`module_put()` 을 한 번 더** 호출한다.

`drivers/media/platform/tegra/camera/tegracam_v4l2.c` (linux-nv-oot)

관측된 커널 로그가 정확히 이 순서다:

```
zedx 10-0020: Error turning off streaming          <- stop_streaming() 실패
WARNING at kernel/module.c:1095 module_put+0x18c   <- 두 번째 module_put
  module_put <- tegracam_v4l2subdev_register <- tegra_channel_set_stream
             <- _vb2_fop_release <- __fput <- do_exit
```

`module_put()` 은 `atomic_dec_if_positive()` 라서 0 에서 멈춘다. 그런데 0 은 모듈이 로드될 때
받는 **base reference 자체가 사라진 상태**다(`MODULE_REF_BASE = 1`). sysfs 는 `atomic - 1` 을
보여주므로 `/sys/module/sl_zedx/refcnt` 가 `-1` 이 된다.

이 기계에서 실측으로 확인했다: 카메라가 열려 있어 sysfs 가 `2` 일 때 실제 atomic 은 `3` 이다.

### 그래서 재부팅밖에 없었던 이유

`rmmod` 는 base reference 를 되돌려받아야 성공한다. 그게 없으면 영원히 실패하고,
`systemctl restart zed_x_daemon` 이 하는 일이 정확히 rmmod + insmod 이므로 조용히 무효가 된다.
`CONFIG_MODULE_FORCE_UNLOAD` 도 꺼져 있어 `rmmod -f` 조차 없다.

### 잃어버린 참조를 되돌려주는 도구

`tools/zedx_refcnt/` — `driver_find("zedx", &i2c_bus_type)->owner` 로 대상 모듈에 도달하고
(모듈 리스트 순회 없음, 미export 심볼 없음), 이름이 일치하고 LIVE 일 때만 동작한다.

```bash
cd ~/robot_ws/tools/zedx_refcnt && make
sudo insmod zedx_refcnt.ko target=sl_zedx driver=zedx repair=1
sudo rmmod zedx_refcnt
cat /sys/module/sl_zedx/refcnt      # -1 -> 0
```

검증(`tools/zedx_refcnt/test_zedx_refcnt.sh`, 12/12): 유휴 모듈 `sl_zedxpro` 에서
`unsafe_break=1` 로 `refcnt=-1` 을 **재현**하고 `repair=1` 로 정확히 되돌렸다. 잘못된 드라이버
이름·이름 불일치는 아무것도 건드리지 않고 거부하며, `delta<0` 은 base reference 아래로 내려가지
않는다(도구가 스스로 이 손상을 만들 수 없다).

### 복구 사다리

```bash
sudo bash ~/robot_ws/scripts/zedx_recover.sh --plan   # 무엇을 할지만 출력, 실행 안 함
sudo bash ~/robot_ws/scripts/zedx_recover.sh          # 열리는 즉시 중단
```

| # | 단계 | 무엇을 되돌리나 |
|---|---|---|
| 1 | stop-clients | 카메라를 잡은 프로세스 정리. 하나라도 살아 있으면 아래 단계는 위험하다 |
| 2 | restart-nvargus | argus 에 남은 고아 캡처 세션 |
| 3 | rebind-sensors | `zedx` i2c 클라이언트(10-0020, 10-0028) unbind/bind → v4l2 subdev 재등록. **모듈 언로드가 필요 없어 refcnt 손상과 무관하게 동작한다** |
| 4 | repair-refcnt | `refcnt < 0` 일 때만. base reference 복원 → rmmod 가 다시 합법이 됨 |
| 5 | reload-drivers | `systemctl restart zed_x_daemon` = 진짜 rmmod+insmod. 로그에 `is in use` / `File exists` 가 없는지 **검증**한다 |

**순서 강제(`scripts/test_zedx_recover.sh` 8/8)**: 4단계는 반드시 5단계보다 먼저다.
이 커널은 `panic_on_oops=1` 이고, atomic refcnt 가 0 인 상태의 `rmmod` 는 이론상
`try_release_module_ref()` 의 `BUG_ON(ret < 0)` 에 걸린다. 2026-09-08~09 에 refcnt=-1 상태로
데몬을 3회 이상 재시작했지만 패닉은 나지 않았으므로(userspace `rmmod` 가 먼저 포기한 것으로
보인다) 실측된 위험은 아니다. 그래도 대가가 큰 쪽이므로 가드는 유지한다.

### 실검증 (2026-09-09 13:40, 동작 중인 캐빈 카메라로)

증거: `~/data/zedx_validation-20260909-134011/`

1. **clean stop** — Ctrl-C 한 번으로 `=== CLOSING CAMERA ===` → `process has finished cleanly`.
   `escalating to 'SIGTERM'` 0회, 커널 손상 0회, `refcnt 2 -> 0`, `VERDICT=HEALTHY`.
2. **5단계가 진짜 재로드를 한다** — `systemctl restart zed_x_daemon` 직후 커널이 **전체 재프로브**를
   했다(부팅 때와 같은 순서):

   ```
   13:40:17 sl_max96712 9-0029: gmsl_pipeline_setup: Camera connected to GMSL port 2 / 3
   13:40:17 sl_max96712 9-0029: pipes_setup: camera pipeline operational
   13:40:22 zedx 9-0020 / 9-0028: zedx_probe: Serial Number : 45233238
   13:40:23 zedx 10-0020 / 10-0028: zedx_probe: Serial Number : 49749405
   ```

   데몬 로그에 `is in use` / `File exists` 0건 → rmmod/insmod 가 조용히 성공했다.
   **refcnt >= 0 이면 벤더 복구 경로는 실제로 작동한다**(refcnt 가 음수일 때만 무효화된다).
3. **재로드 직후 SDK 가 카메라를 연다** — 두 카메라 모두 `AVAILABLE`,
   `OPEN_RESULT SUCCESS`, `GRAB SUCCESS`, `FRAME 1920 1200`.
4. **재런치** — `ros2 topic hz` `average rate: 9.844`.

### 그래도 남은 구멍 (정직하게)

- 3단계 `rebind-sensors` 는 한 번도 실행되지 않았다(2단계에서 이미 복구됐거나 필요가 없었다).
- 위 검증은 **정상 상태**에서 4→5 단계의 *메커니즘*을 증명한 것이다. refcnt 복구(4)와 모듈
  재로드(5)가 각각 작동함은 증명됐지만, **실제 wedge 상태에서 그 조합이 argus/VI 를 풀어내는지**는
  여전히 미증명이다. 다만 남은 논리적 간극은 "부팅과 동일한 전체 재프로브가 wedge 를 푸는가" 하나뿐이고,
  재부팅이 항상 고쳤다는 사실이 그 쪽을 강하게 지지한다.

### 부수 발견: 5초 타임아웃은 정상 종료에서는 문제가 아니다

이번 clean stop 은 **옛 5초 설정 그대로**였는데도 에스컬레이션 없이 끝났다. 즉 `sl::Camera::close()`
는 정상 상태에서 5초 안에 끝난다. 5초 초과는 **argus 가 이미 죽어 close 가 매달릴 때**만 일어난다
(2026-09-09 12:00 관측). 따라서 30초 타임아웃은 평상시를 위한 것이 아니라 **그 병적인 경우에
SIGKILL 로 카메라를 못 놓고 죽는 것을 막는 안전장치**다.

## 8. 예방 — 애초에 wedge 를 만들지 않기

### 원인 사슬 (2026-09-09 10:55~10:57 실측)

```
10:55:49  SCF: 5 buffers still pending during EGLStreamProducer destruction
          = 스트리밍 중이던 클라이언트가 카메라를 놓지 않고 죽음
10:56:05  [ZED-X Daemon] Restart NVArgus Daemon      <- 데몬이 스스로 재시작 (ZEDX#1#8#FROZEN)
10:56:04  zedx 10-0028: Error turning off streaming  <- 스트리밍 중에 argus 가 사라짐
10:57:16  [ZED-X Daemon] Restart NVArgus Daemon      <- 두 번째
10:57:16  WARNING module.c:1095 module_put           <- refcnt = -1 확정
```

즉 **사용자의 Ctrl-C 가 아니라 ZED-X 데몬 자신의 워치독**이 방아쇠를 당겼다. 데몬은 카메라가
`FROZEN` 이라고 판단하면 스트리밍 중이든 말든 nvargus 를 재시작한다. 이 동작을 끄는 설정은
`/etc/systemd/system/zed_x_daemon.service` 에도 데몬 바이너리에도 없다(preload/postload 훅뿐).

따라서 예방은 **FROZEN 상태를 만들지 않는 것**, 즉 클라이언트가 카메라를 항상 깨끗이 놓고
죽게 하는 것이다.

### 적용한 변경

`launch/zedx_cabin.launch.py` 에 종료 유예 시간을 명시했다:

```python
SetLaunchConfiguration('sigterm_timeout', '30'),
SetLaunchConfiguration('sigkill_timeout', '10'),
```

launch 의 기본값은 5초인데 ZED 노드는 그 안에 `sl::Camera::close()` 를 끝내지 못한다.
실측(2026-09-09 12:00):

```
process[component_container_isolated-2] failed to terminate '5' seconds after
receiving 'SIGINT', escalating to 'SIGTERM'
```

5초 뒤 SIGTERM, 다시 5초 뒤 SIGKILL → 카메라를 놓지 못한 채 죽음 → FROZEN → wedge.
회귀 테스트: `scripts/test_zedx_launch_shutdown.py`.

### 운영 수칙

- ZED 노드는 **Ctrl-C 한 번**, 그리고 `process has finished cleanly` 를 눈으로 확인한다.
  안 끝난다고 Ctrl-Z 로 밀어두고 새 런치를 띄우면 중지된 프로세스가 카메라를 계속 붙잡는다.
- **노드를 내린 직후** `bash ~/robot_ws/scripts/zedx_health.sh` 를 돌린다. `HEALTHY` 가 아니면
  다음 런치를 띄우지 말고 `zedx_recover.sh` 로 간다.
- **스트리밍 중에는 어떤 데몬도 재시작하지 말 것.** 이게 이번 사고를 만든 동작이다.

## 9. tmux 런처(`sensors`)에 붙인 자동 점검 (2026-09-09)

`sensors start` 는 이제 tmux 세션을 만들기 **전에** 카메라 스택을 점검하고, 안전할 때만 스스로 복구한다.

```bash
sensors start     # 점검 -> (필요하고 안전하면) 복구 -> 런치
sensors check     # 점검만 (별칭: scheck)
sensors stop      # 실제로 종료될 때까지 기다린 뒤 세션을 죽인다
```

### 게이트: 언제 자동 복구가 도는가

`scripts/zedx_preflight.sh` 의 종료 코드가 `sensors` 의 분기 계약이다.

| 코드 | 뜻 | `sensors` 의 반응 |
|---|---|---|
| 0 | 이미 정상, 또는 복구 성공 | 그대로 런치 |
| 2 | 복구가 필요하지만 **안전하지 않음** | 무엇을 멈춰야 하는지 출력하고 런치는 진행 |
| 1 | 복구했는데도 wedge | 재부팅이 남았다고 알리고 런치는 시도 |

**자동 복구를 하지 않는 경우** (`scripts/test_zedx_preflight.sh` 5/5 로 강제):

- 카메라를 잡은 프로세스가 하나라도 살아 있을 때 — 복구는 그것을 죽인다. 먼저 `sensors stop`.
  (`sensors restart` 는 stop 이 먼저라 두 번째 단계에서 자동으로 복구가 돈다.)
- root 를 못 얻고 tty 도 없을 때 — sudo 프롬프트에서 매달리지 않는다.

### 같이 고친 것: `sensors stop` 의 3초 고정 sleep

원래 코드는 Ctrl+C 를 보내고 **3초 뒤 무조건** 세션을 죽였다:

```bash
SHUTDOWN_GRACE_SECONDS=3
sleep "$SHUTDOWN_GRACE_SECONDS"
tmux kill-session ...      # -> SIGHUP 몰살
```

ZED 노드가 `=== CLOSING CAMERA ===` 를 끝내는 데는 그보다 오래 걸린다. launch 의 SIGTERM
에스컬레이션(5초, 지금은 30초)이 시작되기도 전에 세션이 죽는다. 즉 **`sdown` / `srestart` 자체가
이 사고를 만들어온 경로**다. 세션 생성 시각과 wedge 시각이 매번 붙어 있던 이유이기도 하다.

이제는 프로세스가 실제로 사라질 때까지(최대 45초) 기다리고, 초과하면 무엇이 남았는지 경고한다.
회귀 테스트 `scripts/test_sensors_zedx.sh` 는 throwaway tmux 세션과 마커 프로세스로
정상 종료 경로와 타임아웃 경로를 둘 다 실행해 확인한다(실제 카메라는 건드리지 않는다).

### 수정한 파일

- `~/.local/bin/sensors` — git 관리 밖이라 백업을 남겼다: `~/.local/bin/sensors.bak.20260909-141728`
- `~/.bashrc` — `scheck` 별칭 추가
- 로그인 셸마다 점검을 돌리지는 **않는다**. 점검은 카메라를 띄우는 순간에만 의미가 있고,
  매 셸마다 돌면 소음이자 sudo 프롬프트 지뢰다.
