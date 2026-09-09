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
| `REBOOT_REQUIRED` | 2 | `sl_zedx` 모듈 use-count 파손 | **재부팅 외 방법 없음** |

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

**따라서 `cat /sys/module/sl_zedx/refcnt` 가 음수면 2·3단계는 건너뛰고 바로 재부팅한다.**
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
