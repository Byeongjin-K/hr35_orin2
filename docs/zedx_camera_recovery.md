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
- `~/.bashrc` — 별칭 한 줄 (기계를 다시 세팅할 때 그대로 넣으면 된다):
  ```bash
  alias scheck='sensors check'
  ```
- `~/.local/bin/sensors` 는 이제 저장소 사본을 가리키는 심볼릭 링크다:
  `~/.local/bin/sensors -> ~/robot_ws/scripts/sensors` (원본이 하나뿐이라 갈라지지 않는다).
  되돌리려면: `rm ~/.local/bin/sensors && cp ~/.local/bin/sensors.bak.20260909-141728 ~/.local/bin/sensors`
- 로그인 셸마다 점검을 돌리지는 **않는다**. 점검은 카메라를 띄우는 순간에만 의미가 있고,
  매 셸마다 돌면 소음이자 sudo 프롬프트 지뢰다.

## 10. 2026-09-14 사고 — 이 도구가 커널을 패닉시켰다

`sensors start` 의 자동 복구가 돌면서 기계가 **커널 패닉으로 재부팅**되어 원격 SSH 가 끊겼다.
증거는 ramoops 에 그대로 남았다: `~/data/zedx_incidents/20260914-panic/`.

```
[4652.332] zedx 10-0020: zedx_probe: ar0234 initialization failed   <- unbind 뒤 re-bind 실패
[4652.400] zedx 10-0028: zedx_probe: ar0234 initialization failed
[4652.461] pc : __pi_memcmp   lr : strnstr
           tegra_channel_set_power [tegra_camera] <- __fput <- do_exit
           Comm: TempBufferAcqui                  <- argus 캡처 스레드 종료
[4653.479] Kernel panic - not syncing: Oops: Fatal exception
```

사슬: 2단계가 `nvargus-daemon` 을 재시작하고 probe 가 argus 세션을 새로 만든다 →
3단계 `rebind-sensors` 가 **그 세션 밑에서 드라이버를 unbind** → re-bind 가 실패해 v4l2 subdev 가
사라짐 → 130ms 뒤 살아있던 argus 스레드가 종료되며 없어진 subdev 를 참조 → oops →
`panic_on_oops=1` 이므로 즉시 패닉·재부팅.

"카메라 클라이언트 없음" 게이트가 이걸 막지 못한 이유: **v4l2 fd 를 실제로 쥐고 있는 것은
`nvargus-daemon`** 인데 클라이언트 패턴(`component_container|ZED_Explorer|...`)에 없었다.

### 고친 것

1. **`rebind-sensors` 룽 삭제.** 한 번도 카메라를 살린 적이 없고, 커널을 죽인 전력이 있다.
2. **파괴적 스크립트의 기본값을 dry-run 으로.** 같은 날 두 번째 사고는 테스트가
   `zedx_recover.sh --safe --plan` 을 호출했는데 파서가 `$1` 만 보느라 `--plan` 을 놓쳐
   **진짜 사다리를 실행**한 것이었다(스트리밍 중인 노드를 SIGKILL → `refcnt=-1`).
   이제 실행하려면 `--run` 이 필요하고, 모르는 플래그는 exit 64 로 거부한다.
3. **무인 실행은 커널을 건드리지 않는다.** `sensors start` 의 preflight 는
   `zedx_recover.sh --safe --run` 을 부르고, `--safe` 는 사용자 공간 룽
   (stop-clients, restart-nvargus)에서 멈춘다. refcnt 복구·드라이버 재로드처럼 커널을 만지는
   단계는 **사람이 직접** `sudo zedx_recover.sh --run` 으로 실행한다.

### 남은 위험

`panic_on_oops=1` 이므로 이 스택에서 커널 oops 는 곧 재부팅이다. 값을 바꾸지는 않았다 —
카메라 드라이버가 oops 난 뒤 계속 도는 쪽이 더 나쁘다. 대신 **무인 경로가 커널을 건드리지 않게**
막는 방향을 택했다.

## 11. 반증: 모듈 재로드는 재부팅과 동등하지 않다 (2026-09-14 실측)

7장은 "남은 논리적 간극은 부팅과 동일한 전체 재프로브가 wedge 를 푸는가 하나뿐이고, 재부팅이
항상 고쳤다는 사실이 그쪽을 강하게 지지한다"고 적었다. **그 추론은 틀렸다.** 실제 wedge 에서
사다리를 끝까지 돌린 결과:

| 단계 | 결과 |
|---|---|
| repair-refcnt | 성공. `/sys/module/sl_zedx/refcnt` `-1 → 0` |
| reload-drivers | **진짜 재로드됨.** `sl_max96712 9-0029: sl_max96712_probe: enter/success`, `zedx_probe: Serial Number` 4줄 전부 재출력, 데몬 로그에 `is in use`/`File exists` **0건** |
| `sl::Camera::open()` | **실패.** argus: `NvPclStartPlatformDrivers: Failed to start module drivers`, `NvPclOpen: PCL Open Failed. Error: 0xf`, `SCF: Error BadParameter: Sensor could not be opened` (48회) |
| 그 뒤 refcnt | 실패한 open 이 tegracam 이중 `module_put` 을 다시 타서 **-1 로 복귀** |

결론: **고장은 모듈 계층 아래(VI/NVCSI/카메라 RTCPU)에 있다.** 모듈을 완전히 내렸다 올려도
그 상태는 남는다. 사용자 공간에서 그것을 리셋하는 방법은 (조사 범위 안에서) 존재하지 않는다.

### 그래서 지금 사다리를 어떻게 쓰나

- **`--safe`(무인, `sensors start` 가 부르는 것)**: stop-clients + restart-nvargus. 고아 argus
  세션은 이걸로 실제 풀린다. 여기까지는 값어치가 있다.
- **3·4단계(repair-refcnt, reload-drivers)**: 실제 wedge 에서 한 번 시도했고 **카메라를 살리지
  못했다.** 3분이 걸리고 실패한 open 이 refcnt 를 다시 깨뜨린다.
  `zedx_health.sh` 가 `REBOOT_REQUIRED` 를 내면 **그냥 재부팅하는 편이 빠르다.**
- 3·4단계를 남겨둔 이유는 단 하나, 다른 종류의 wedge(모듈 상태만 깨진 경우)에서는 유효할 수
  있기 때문이다. 하지만 2026-09-14 형태의 고장에는 듣지 않는다.

### 정직한 현재 상태

`CAMERA STREAM FAILED TO START` 의 이 형태에 대해 **검증된 무재부팅 복구 수단은 없다.**
있는 것은 (a) 애초에 wedge 를 만들지 않는 예방(clean stop, 워치독 회피)과
(b) 30초 안에 "재부팅이 필요하다"를 확정해주는 판정이다.

## 12. 정정 — FROZEN 은 원인이 아니라 증상이었다 (2026-09-14 오후, 무재부팅 복구 성공)

11장은 "모듈 재로드로도 안 풀리니 재부팅밖에 없다"고 결론지었다. **그것도 틀렸다.**
같은 날 오후 재부팅 없이 카메라를 되살렸다.

### 무엇이 진짜였나

`/sys/module/sl_zedx/refcnt = -1` 은 atomic 0 이다. `try_module_get()` 은 `atomic_inc_not_zero`
이므로 **0 에서는 실패한다.** tegracam 의 스트림 시작 경로가 바로 그것을 호출하므로 CSI 스트림이
영영 켜지지 않고, 카메라 MCU 는 호스트를 기다리다 스스로 `FROZEN` 을 보고한다.

```
Port 1 OPENING for CAM ModeliD 8
Port 1 CLOSING for CAM ModeliD 8
Received invalid message: "ZEDX#1#8#FROZEN"
```

판별 증거: **boom 카메라(다른 GMSL 포트, 다른 하드웨어)도 똑같이 FROZEN** 이었다. 두 카메라의
공통분모는 하드웨어가 아니라 `sl_zedx` 모듈 하나뿐이다. 즉 카메라가 고장 난 것이 아니었다.
`AVAILABLE` 은 I2C 열거만 성공했다는 뜻이라 이 판단에 쓰면 안 된다.

### 실제로 들은 순서

```
1. systemctl restart nvargus-daemon        # argus 가 쥔 /dev/video fd 를 놓게 한다
2. insmod zedx_refcnt.ko ... repair=1      # 잃어버린 base reference 하나를 되돌린다
3. 곧바로 연다
```

```
refcnt before repair: -1
after repair:          0
refcnt immediately before open: 0
OPEN_RESULT SUCCESS / GRAB SUCCESS / FRAME 1920 1200
[12:37:07] Port 1 OPENING -> Port 1 Running      <- 그날 처음 나온 Running
ros2 topic hz ... average rate: 9.998
```

### 12:21 시도가 실패한 이유 (중요)

그때도 repair 는 성공했다. 그런데 곧바로 **reload-drivers** 를 돌렸고, `zed_x_daemon` 이 재시작되면서
**스스로 GMSL 포트를 열려고 시도**한다. 그 시도가 실패하면서 방금 되돌려놓은 참조를 그대로 태웠다.
probe 는 그 뒤에 돌았으니 실패할 수밖에 없었다.

**그래서 사다리에서 `reload-drivers` 를 기본 경로에서 뺐다.** 지금은 repair 직후 곧바로 카메라를
열어보고, 그래도 안 되면 그때만 reload 로 간다.

### 판정 변경

`refcnt < 0` 은 이제 `REBOOT_REQUIRED` 가 아니라 **`RECOVERABLE`(exit 1)** 이다.
`zedx_health.sh` 는 `sudo zedx_recover.sh --run` 을 안내하고, "이걸 고치겠다고 zed_x_daemon 을
재시작하지 말라"고 경고한다. `REBOOT_REQUIRED` 는 이제 **드라이버가 아예 안 올라온 경우**에만 쓴다.

### 무인 경로에서 허용되는 것

`--safe` (=`sensors start` 가 부르는 것)는 stop-clients, restart-nvargus, **repair-refcnt** 까지 한다.
repair 는 atomic 증가 하나이고 BUG_ON 경로가 없어 무인 실행이 안전하다. 모듈을 내리는 rung 은
여전히 사람이 지켜보며 `sudo zedx_recover.sh --run` 으로만 돈다.

## 13. 최종 모델 — 고장은 2단계다 (2026-09-14 저녁, 반증으로 확정)

12장은 "refcnt 만 복구하면 열린다"고 했다. **필요조건이지 충분조건이 아니다.**

### 반증한 실험

재시도 루프를 PID 로 전부 제거(zed 프로세스 0, `/dev/video` 점유 0) → `nvargus-daemon` 재시작 →
refcnt 복구 → **6초간 refcnt 가 0 을 유지하는 것까지 확인**(아무도 태우지 않음) → open.

```
refcnt 1s:0 2s:0 3s:0 4s:0 5s:0 6s:0
13:10:50 Port 1 OPENING
13:11:11 Port 1 CLOSING          <- 21초 침묵 = argus 타임아웃
13:11:29 UNDERFLOW (PID 122753 = 실패한 probe 자신)
13:12:06 "ZEDX#1#8#FROZEN"
```

완전히 깨끗한 상태에서도 열리지 않았다. 따라서 refcnt 는 고장의 **한 층**일 뿐이다.

### 2단계 모델

| 단계 | 상태 | 복구 |
|---|---|---|
| 1단계 | `refcnt < 0` 만 깨짐. 카메라 MCU 는 아직 멀쩡 | **무재부팅 복구 가능.** restart-nvargus → repair-refcnt → 곧바로 open (2026-09-14 12:35 성공) |
| 2단계 | 실패한 open 이 반복되어 **MCU 가 FROZEN 에 고착** | **재부팅만.** PoC 전원 재인가 외에 방법 없음 |

부팅 이후 누적(2026-09-14):

```
Port Running : 3   (마지막 12:37:07 = 1단계에서 복구에 성공한 순간)
Port OPENING : 17
FROZEN       : 32
```

12:37 이후 14번의 open 시도가 **전부 Running 에 도달하지 못했다.** 1단계에서 잡지 못하고
재시도를 반복하면 2단계로 굳는다.

### 그래서 운영 규칙

- **`zedx_health.sh` 가 뭔가 말하면 즉시 `zedx_recover.sh --run`.** 늦을수록 2단계로 굳는다.
- **안 열린다고 런치를 반복하지 말 것.** 실패한 open 1회 = MCU 를 FROZEN 쪽으로 한 칸 미는 것.
- 복구 후에도 `Port ... Running` 이 안 뜨면 2단계다. 그때는 재부팅이 가장 빠르다.
- 판정 근거: `journalctl -u zed_x_daemon | grep -c 'Running for CAM'` 가 늘어나면 1단계 복구 성공.

### 이번에 같이 고친 코드 결함

1. `zedx_recover.sh` 가 `systemctl is-active` / `journalctl` 을 `$SUDO` 로 호출했다. 이 둘은
   `/etc/sudoers.d/zedx-recovery` 화이트리스트에 없어 **비밀번호 프롬프트에서 멈춘다** —
   `sensors start` 의 무인 경로가 거기서 영영 매달렸다. root 가 필요 없는 명령이므로 sudo 를 뺐다.
2. `zedx_preflight.sh` 의 root 검사가 `sudo -n true`(무제한 무비번)를 봤다. 우리는 명령 4개만
   허용하므로 `sudo -n -l <그 명령>` 으로 바꿨다.
3. insmod 경로에 `..` 이 들어가 sudoers 의 리터럴 매칭에 걸리지 않았다. 정규 경로로 바꿨다.
4. `stop-clients` 가 `ros2 launch` 감독 프로세스를 못 잡았다(패턴이 `component_container` 뿐).
   살아남은 감독이 6초마다 재시도하며 **복구를 1초 만에 되돌렸다**. fd 가드도 재시도 사이
   빈틈에서 `0` 으로 통과했다. 정리는 패턴이 아니라 **PID 지목**으로 해야 한다
   (패턴 kill 은 같은 문자열을 포함한 진단 셸까지 죽인다).

### sudoers

`/etc/sudoers.d/zedx-recovery` 에 복구가 쓰는 명령 4개만 NOPASSWD. `kimm` 은 원래 `ALL:ALL` 이라
권한이 늘어난 것이 아니라 프롬프트만 사라진 것이고, 평문 비밀번호는 어디에도 저장하지 않았다.
되돌리기: `sudo rm /etc/sudoers.d/zedx-recovery`.

## 14. 2026-09-18 — 복구는 성공했는데 스크립트가 "reboot required" 라고 했다

**한 줄**: `zedx_recover.sh` 의 STEP 4 대기가 **직전 재시작의 로그**를 보고 즉시 통과해,
드라이버가 언로드된 순간에 probe 를 쏘고 멀쩡한 스택을 재부팅 대상으로 판정했다.

### 실측 타임라인

```
09:49:00 OPENING -> 09:49:01 Running          (정상 시작)
     ...  4시간 59분 연속 동작 ...
14:48:25 4 buffers still pending during EGLStreamProducer destruction x2   (클라이언트 teardown)
14:48:40 kernel: zedx 10-0020/10-0028: Error turning off streaming          (8장의 그 시그니처)
14:48:40 ZED-X Daemon: Restart NVArgus Daemon
14:48:44 CLOSING -> 14:49:17 ZEDX#1#8#FROZEN
15:40:44 재기동 CAMERA STREAM FAILED TO START x6 -> 15:41:13 Camera detection timeout
--- 여기서 sudo zedx_recover.sh --run ---
15:54:28 STEP 2 restart-nvargus. 데몬이 이에 반응해 스스로 드라이버 리로드
15:54:39   ZED-X Driver loaded            <<< 이 줄이 다음 단계를 망친다
15:55:49 STEP 4 systemctl restart zed_x_daemon
15:55:49   대기 루프가 --since '-2min' 창에서 15:54:39 의 'Driver loaded' 를 보고 즉시 break
15:55:50   ZED-X Driver removed           <<< probe 는 지금 실행됐다. 드라이버가 없다
           -> ZED-X Daemon 로그에 OPENING 0건. probe 실패. exit 7 "reboot required"
15:56:00   ZED-X Driver loaded + Restarting NVArgus + Created Pub Endpoint  (진짜 완료, 11초 늦게)
15:59:42 사용자가 런치 -> OPENING -> Running  (첫 시도에 성공. 재부팅은 애초에 불필요했다)
```

### 근본 원인

`journalctl --since '-2min'` 은 **상대 시간창**이라 직전 재시작의 로그를 함께 잡는다.
STEP 2 가 argus 를 재시작하면 ZED-X 데몬이 스스로 드라이버를 리로드하므로, STEP 4 가 자기
재시작을 기다릴 때 창 안에는 이미 `ZED-X Driver loaded` 가 들어 있다.
`is in use|File exists` 검사도 같은 오염된 창을 봤다.

**고친 방법**: systemd 가 서비스 시작마다 새로 발급하는 `InvocationID` 로 범위를 좁혔다.
`systemctl show -p InvocationID --value zed_x_daemon` 으로 이번 시작의 ID 를 얻고
`journalctl -u zed_x_daemon _SYSTEMD_INVOCATION_ID=<id>` 만 본다. 시간창은 ID 를 못 얻을 때의 폴백.

**추가로**: `ZED-X Driver loaded` 는 끝이 아니다. 데몬은 그 직후 NVArgus 를 재시작하므로,
그 틈에 쏜 probe 는 카메라에 닿지 못한다. 이제 `Created Pub Endpoint`(데몬의 마지막 기동 줄)
까지 기다리고, `nvargus-daemon` 이 active 가 될 때까지도 기다린 뒤에 probe 한다.
대기가 예산 내에 끝나지 않으면 `exit 6` 으로 **명시적으로 보고**한다 — 조용히 진행하지 않는다.

### 같이 드러난 결함 두 개

1. **`stop-clients` 가 실패를 조용히 통과했다.** `component_container_isolated[886377]` 이
   STEP 1 이후에도 살아서 argus 에 재연결했다(15:54:55, 15:55:35 `Connection established`).
   SIGKILL 뒤 확인이 없었기 때문이다. 감독(`ros2 launch`)이 컨테이너를 되살리므로 컨테이너만
   죽여서는 정리되지 않는다. 이제 SIGKILL 후에도 남아 있으면 `exit 8` 로 **중단**하고 무엇이
   살아 있는지 출력한다. 사다리의 나머지는 "아무도 카메라를 안 만진다" 를 전제로 하므로,
   살아 있는 클라이언트를 상대로 돌리면 움직이는 표적을 쫓게 된다.
   (STEP 2 의 `camera fds held` 가드는 이걸 못 잡는다. `/dev/video*` 를 쥐는 건 argus 이지
   클라이언트가 아니다.)
2. **`probe_ok` 가 실패 사유를 버렸다.** `2>/dev/null` 때문에 "카메라가 죽었다" 와
   "너무 일찍 찔렀다" 를 구분할 수 없었다 — 이번 사건의 애매함이 정확히 그것이었다.
   이제 출력을 `PROBE_LAST` 에 보관하고 최종 실패 메시지에 마지막 5줄을 찍는다.

### `zedx_health.sh` 도 같은 종류의 오탐이 있었다

복구 직후 16:xx 에 health 가 `argus faults : 2` 로 `RECOVERABLE` 을 냈다. 그 2줄은 15:55:18 의
`EGLStreamProducer destruction` — **복구 스크립트 자신이 만든 것**이었다. `-15min` 시간창은
"스택이 wedge 됐다" 와 "방금 우리가 argus 를 재시작했다" 를 구분하지 못한다.
이제 **지금 돌고 있는 argus 인스턴스**의 로그만 센다
(`_SYSTEMD_INVOCATION_ID=$(systemctl show -p InvocationID --value nvargus-daemon)`).
죽은 인스턴스의 fault 는 과거를 설명할 뿐 현재 상태가 아니다.
출력도 `... line(s) in the running nvargus-daemon instance` 로 바뀌었다.

### 운영 수칙 (갱신)

- **복구 직후 바로 런치하지 말고, 데몬 기동이 끝났는지 보고 나서 띄운다.** 판단 줄은
  `journalctl -u zed_x_daemon -b 0 | tail` 의 `Created Pub Endpoint`. 스크립트는 이제 이걸
  기다리지만, 수동으로 할 때도 같은 기준이다.
- **`FAILED: reboot required` 를 그대로 믿지 말고 커널 로그를 먼저 본다.**
  `journalctl -k -b 0 | grep 'zedx_probe: Serial Number'` 가 4줄(카메라 2대 x 좌우) 나오고
  `sl_max96712 ...: camera pipeline operational` 이 보이면 **드라이버 스택은 살아 있다.**
  2026-09-18 이 정확히 그 경우였고, 그 상태에서 런치 한 번으로 복구됐다.
- 여전히 유효: 안 열린다고 런치를 **반복하지 말 것**. 실패한 open 1회가 MCU 를 FROZEN 쪽으로 민다.

### 검증

`scripts/test_zedx_recover.sh` 27/27, `scripts/test_zedx_health.sh` 7/7,
`scripts/test_zedx_preflight.sh` 6/6 (순차 실행 2회 연속). RED 를 먼저 잡고 고쳤다:
대기 테스트는 수정 전 `rc=0 polls=1`(직전 로그를 보고 즉시 통과) 로 사건을 재현했고,
수정 후 `polls=5`(기동 완료까지 대기) 로 통과한다.

**주의**: 이 테스트들은 **순차로** 돌려야 한다. `test_zedx_preflight.sh` 와
`test_sensors_zedx.sh` 는 의도적으로 실제 `pgrep`/`tmux` 를 타므로, 동시에 돌리면 서로의
프로세스를 잡아 가짜 실패가 난다(실측: 병렬 실행 시 preflight 5/2, 순차 6/0).

---

## 15. 2026-09-21 — 무재부팅 복구 완성. 빠져 있던 건 **카메라 MCU 리셋**이었다

13장의 "2단계(MCU FROZEN 고착)는 재부팅만" 은 **틀렸다**. 재부팅 0회로 복구했고
(17:08:22 `OPEN SUCCESS` / `FRAME 1920x1200`, 런치 후 compressed 9.804Hz), 그 순서를
`zedx_recover.sh` 에 넣었다. 이제 **`zedx_recover.sh --run` 한 번이면 끝난다.**

### 반증 1 — 사다리가 자기 발등을 찍고 있었다

옛 순서는 `repair-refcnt → open 프로브 → (실패 시) reload-drivers` 였다. **그 중간 프로브가
문제다.** wedge 된 카메라는 open 이 반드시 실패하고, 실패한 teardown 이 tegracam 의 이중
`module_put` 버그를 때려 방금 복원한 참조를 그 자리에서 태운다. 실측:

| 시각 | 사건 |
|---|---|
| 17:00:08 | repair 로 refcnt **0** 확보 |
| 17:00:08 | 프로브 실패 → `Error turning off streaming` ×2 → `module_put` 언더플로 (PID 50505) |
| 17:00:09 | refcnt **-1** 로 복귀 |
| 17:00:09 | 그 상태로 리로드 → `sl_max9295 is in use by: sl_zedx`, `sl_zedx.ko: File exists` |
| | → `sl_zedx` 는 **언로드조차 못 했다**. 커널에 새 `Serial Number` 0줄 → `exit 6` |

즉 **`FAILED: reboot required` 는 카메라가 못 산다는 뜻이 아니라, 스크립트가 자기
전제조건을 프로브로 부쉈다는 뜻**이었다. 부수 결함: rung 4 의 panic 가드가 `$refcnt` 의
**프로브 이전 값**(stale)을 봤다 — 실제 -1 인데 0 으로 알고 데몬에 rmmod 를 시켰다.

### 반증 2 — 드라이버를 완전히 재프로브해도 카메라는 안 열린다

프로브를 빼고 `repair → 즉시 데몬 재시작` 으로 **진짜 리로드**를 받아냈다(17:03:20):
rmmod/insmod 거부 0건, 커널 `zedx_probe: Serial Number` **4줄**,
`sl_max96712_probe: success`, `camera pipeline operational` ×2, `[last unloaded: sl_max96712]`,
refcnt 0, `module_put` 경고 0건. **그런데도** 17:04 의 open 은
`(Argus) Error Timeout ... ClientSocketManager.cpp:137` + `ZEDX#1#8#FROZEN` 으로 실패했다.

→ 11장의 "리로드는 재부팅과 동등" 은 **드라이버 스택에 한해서만** 참이다. 호스트가 무엇을 하든
카메라 MCU 는 frozen 으로 남는다. 사다리를 끝까지 돌려도 안 살아나던 진짜 이유가 이것이다.

### 해결 레버

```python
import pyzed.sl as sl
sl.Camera.reboot_from_input(sl.INPUT_TYPE.GMSL)   # -> SUCCESS
```

- 호스트를 안 건드리고 GMSL 링크 너머 **카메라 MCU 를 리셋**한다. 커널 모듈을 안 만지므로
  패닉 위험이 없고 refcnt 도 안 태운다.
- **`sl.Camera.reboot(sn, full_reboot)` 는 USB 전용** — 이 장비에선 `INVALID FUNCTION CALL`.
- MCU 부팅에 **~20초** 필요(리셋 17:07:38 → open 성공 17:08:16). `ZEDX_MCU_SETTLE` 로 조절.
- PoC 전원을 직접 끊을 sysfs 레버는 **없다**(device-tree 에 max96712 pwdn/poc 노드 없음,
  regulator 이름에 poc/cam/gmsl 0개). 그래서 이게 유일한 무재부팅 경로다.

### 새 사다리

```
1 stop-clients     2 restart-nvargus   → 프로브 → 되면 끝
3 repair-refcnt    4 reboot-mcu        → 프로브 → 되면 끝   (--safe 는 여기까지)
5 reload-drivers   → repair → reboot-mcu → 프로브          (최후 수단)
```

- **`reboot-mcu` 가 `reload-drivers` 보다 앞**이다. 커널을 안 건드리는 쪽이 더 싸고 더 안전하며,
  실제로 복구를 끝낸 단계다.
- **repair 와 그 참조를 쓰는 단계 사이에 프로브를 넣지 않는다.** 테스트가 이 구간을 스캔해
  `probe_ok` 가 있으면 실패시킨다.
- rmmod 가드는 **매번 sysfs 를 다시 읽는다**(`repair_refcnt`). 캐시된 값은 믿지 않는다.
- `--safe`(무인)는 모듈을 언로드하지 않으므로 4까지. MCU 리셋은 무인에서도 허용한다.

### 호출법

```bash
~/robot_ws/scripts/zedx_recover.sh --run      # sudo 없이!
```

`sudo bash zedx_recover.sh` 는 **틀린 호출**이다. `/etc/sudoers.d/zedx-recovery` 는 스크립트가
아니라 스크립트가 쓰는 명령 4개를 화이트리스트에 올려둔 것이라, sudo 를 붙이면 비밀번호를
묻고 무인 경로가 멈춘다. `zedx_health.sh` 의 안내 문구도 이에 맞춰 고쳤다.

### 검증

`test_zedx_recover.sh` **34/34**, `test_zedx_health.sh` 7/7, `test_zedx_preflight.sh` 6/6
(순차 실행). 옛 "repair → open → reload" 순서를 강제하던 테스트는 이 세션이 반증했으므로,
반대 성질(복원과 사용 사이 프로브 금지 + `reboot-mcu` 가 `reload-drivers` 앞)을 강제하는
테스트로 교체했다. 실기 검증: `mcu_reboot` 기본 경로가 `MCU_REBOOT SUCCESS` (refcnt 불변),
`--run` end-to-end 가 `RECOVERED after restart-nvargus` / `LADDER_EXIT=0`.

---

## 16. 2026-09-22 — "수동 복구가 대부분 실패한다"의 진짜 이유 두 가지

사용자 보고: "zedx_recover 를 수동으로 해도 안 되는 경우가 많아. 대부분이야." 증거로 원인 **두 개**를
찾았고 둘 다 기존 사다리로는 원리적으로 고칠 수 없는 것이었다.

### 원인 A — `host1x_fence` 모듈이 없으면 SDK 가 세그폴트한다 (카메라 문제가 아니다)

`host1x-fence.ko` 는 **host1x OF modalias 로만 자동 로드**된다. 그 경쟁에서 지는 부팅에는 아예
안 올라오고, `/dev/host1x-fence` 가 없어서 **모든 ZED SDK open 이 `DrmCreateEventPollFd` 안에서
코어 덤프**한다. 센서에 도달하기도 전이다.

2026-09-22 13:13 실측 — 이 상태의 스택은 모든 기존 점검을 통과한다:

| 지표 | 값 |
|---|---|
| `sl_zedx` refcnt | 0 (정상) |
| `module_put` 언더플로 | 0 |
| `Error turning off streaming` | 0 |
| `zedx_probe: Serial Number` | 4 (양쪽 카메라 정상 프로브) |
| FROZEN 보고 | 0 |
| `zedx_health.sh` | **HEALTHY** ← 오진 |
| 실제 `sl::Camera::open()` | **코어 덤프** |

감별 증거: ROS 없이 순수 pyzed open 도 똑같이 덤프했고(`DrmCreateEventPollFd: failed to open
host1x-fence device: -1`), `modprobe host1x_fence` 후 **같은 프로브가** `OPEN SUCCESS` /
`FRAME 1920x1200` / `CLOSED_CLEAN` 을 냈다. 즉 GMSL·MCU·refcnt 와 무관하다.

- 고정: `/etc/modules-load.d/zed-host1x-fence.conf` = `host1x_fence`.
  **실제 재부팅(13:26)으로 검증** — 새 부팅에서 `host1x_fence loaded: 1`, 노드 타임스탬프도 그 부팅.
- 사다리에 **rung 0 `load-fence`** 추가(없으면 `modprobe` 후 즉시 프로브, 되면 거기서 종료).
- `zedx_health.sh` 가 이 상태를 **refcnt 보다 먼저** 판정한다(`RECOVERABLE`, exit 1).
- **판정은 `/proc/modules` 로 한다.** `/dev/host1x-fence` 노드는 rmmod 후에도 devtmpfs 에 남으므로
  노드 존재는 증거가 아니다(실측).
- sudoers 에 `/usr/sbin/modprobe host1x_fence` 추가.

### 원인 B — `stop-clients` 가 런치 감독을 보지 못했다

`CLIENT_PATTERN` 이 `component_container|ZED_Explorer|ZED_Depth_Viewer|ZED_Media_Server` 뿐이라
`ros2 launch ... zedx_cabin.launch.py` **감독 프로세스가 매칭되지 않았다**. 13:17 실측: 컨테이너는
죽고 감독(pid 10955)은 살아 있는데 `client_n=0` → **rung 1 이 통째로 건너뛰어지고** 이후 모든
rung 이 계속 되살아나는 런처를 상대로 돌았다. 사용자가 `sensors` 를 띄운 채 복구를 돌리면
항상 이 경로다 — 그래서 "대부분 실패"였다.

- 패턴에 `zedx_cabin\.launch|zedx_boom\.launch|dual_zedx\.launch` 추가.
- **`hr35_bringup` 을 넓게 매칭하면 안 된다** — Ouster 라이다 브링업까지 죽는다.
  테스트가 두 문자열을 직접 패턴에 물려 이 경계를 고정한다.
- 실기 확인: 같은 상황에서 이제 `STATE refcnt=2 clients=2`, `STEP 1 stop-clients` 가 계획된다.

### 검증

`test_zedx_recover.sh` **41/41**, `test_zedx_health.sh` **10/10**,
`test_zedx_preflight.sh` 6/6 (순차). health 테스트는 이제 `ZEDX_MODULES_FILE` 로 모듈 목록을
**고정**한다 — 안 하면 그 부팅이 fence 를 로드했는지에 따라 판정이 흔들려, 이 테스트가 잡으려는
비결정성이 테스트 자신에 들어온다. 실기: 카메라 9.83~9.89Hz, FROZEN 0, 언더플로 0.

