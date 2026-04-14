# GridmapWithTarget.msg - 타겟 영역을 포함한 그리드맵

std_msgs/Header header
float32[] heights          # 67*34 = 2278개 cell 높이 정보
uint8[] target_mask        # 67*34 = 2278개 타겟 마스크 (0 or 1)
geometry_msgs/Point origin # 그리드 원점 좌표
float32 resolution         # cell 해상도 (0.15m)
uint32 width              # 그리드 폭 (67)
uint32 length             # 그리드 길이 (34)
