# Messages
std_msgs/Header header
builtin_interfaces/Time stamp
string[] gpstime

float64 lat
float64 lon
float64 alt
float64 geo
float64 geo_model   # Geoid from model (such as KNGeoid18)
float64 h_dil       # Horizontal Dilusion
float64 tm_x
float64 tm_y
float64 speed       # VTG km/h
float64 speed_dir   # RMC에서 들어오는 진행방향 정보

# float64 roll
# float64 pitch
float64 heading     # HDT
# float64[] att_var

int8 quality
int8 sat
int8 moving_dir     # 전후진 정보

float64 age         # Age of differential GPS data record


