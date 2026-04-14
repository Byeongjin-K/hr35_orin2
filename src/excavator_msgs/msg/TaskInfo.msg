# TaskInfo.msg - 작업 영역 설정 정보
# excavator_task_config_gui에서 발행

std_msgs/Header header

# 기준 정보 (0.1m 해상도)
# @deprecated ground_height: 이 필드는 현재 사용되지 않습니다. 향후 버전에서 제거 예정.
#                             현재는 호환성을 위해 유지되며, 항상 0.0 값이 전달됩니다.
#                             초기 설계 시 "초기 지면 높이"로 정의되었으나,
#                             실제 구현에서는 user_target_depth와 cell_heights만 사용됩니다.
#
#                             원래 정의 (참고용):
#                               - 초기 지면 높이 (m, 0.1m 단위)
#                               - 생성 과정: base_height(8~15) + noise(N(0,1.5))
#                               - 범위: 0.8~1.5m (일반적)
#                               - 에피소드 시작 시 설정, 에피소드 내 불변
float32 ground_height

float32 task_start_point     # 작업 시작 위치 - x 좌표 (m, 0.15m 단위)

# user_target_depth: 지형 오프셋 값 (m, 음수)
#                    의미: 실제 지형(음수)을 위로 올려서 양의 값 공간으로 변환하는 오프셋
#                    계산: -(실제 굴착 깊이) = -(0.4~1.3m)
#                    범위:
#                      - 이론적: -0.4~-1.3m (-4~-13 그리드)
#                      - 일반적: -0.6~-1.0m (-6~-10 그리드)
#                    예시: 0m 지형을 1m 굴착하는 경우
#                      - user_target_depth = -1.0m (음수로 전달)
#                      - 변환된 지형: 0 - (-1.0) = 1.0m (가상 공간에서 지형 상승)
#                      - trench_target_depth = 0.2m라면, 굴착량 = 0.8m
#                      - 최종 실제 지형: -0.8m (0.8m 굴착됨)
#                    제약 조건: 실제 굴착 깊이 ≤ base_height - 2 (안전 여유 0.2m)
float32 user_target_depth

# 작업 영역 정보 (2×20 cells = 40 cells)
# cell_heights: 각 셀의 현재 높이 (m, 0.1m 단위)
#               매 스텝마다 업데이트되는 동적 값
#               굴착 진행에 따라 감소
#               KIMM-Project_end 업데이트: TRENCH_MAX_LENGTH 8→20으로 증가
float32[40] cell_heights

# 메타데이터
uint32 grid_width            # 전체 Grid 너비 (67)
uint32 grid_length           # 전체 Grid 길이 (34)
float32 cell_size            # Cell 크기 (0.15m)
float32 height_resolution    # 높이 해상도 (0.1m)
