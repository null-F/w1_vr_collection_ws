"""FFG 手套协议、通道和通信时序常量。"""

FRAME_HEADER = 0x5D
MAX_FRAME_DATA_SIZE = 255
JOINT_COUNT = 21
MIN_ANGLE_DEG = 0.0
MAX_ANGLE_DEG = 360.0
ANGLE_UNIT = "deg"
STABILITY_THRESHOLD_DEG = 1.718873

JOINT_NAMES = (
    "thumb_abd_0",       # 0  拇指侧摆0
    "thumb_abd_1",       # 1  拇指侧摆1
    "thumb_root",        # 2  拇指指根
    "thumb_mid",         # 3  拇指指中
    "thumb_tip",         # 4  拇指指尖
    "index_abd",         # 5  食指侧摆
    "index_root",        # 6  食指指根
    "index_mid",         # 7  食指指中
    "index_tip",         # 8  食指指尖
    "middle_abd",        # 9  中指侧摆
    "middle_root",       # 10 中指指根
    "middle_mid",        # 11 中指指中
    "middle_tip",        # 12 中指指尖
    "ring_abd",          # 13 无名指侧摆
    "ring_root",         # 14 无名指指根
    "ring_mid",          # 15 无名指指中
    "ring_tip",          # 16 无名指指尖
    "pinky_abd",         # 17 小指侧摆
    "pinky_root",        # 18 小指指根
    "pinky_mid",         # 19 小指指中
    "pinky_tip",         # 20 小指指尖
)

JOINT_LABELS_ZH = {
    0: "拇指侧摆0",
    1: "拇指侧摆1",
    2: "拇指指根",
    3: "拇指指中",
    4: "拇指指尖",
    5: "食指侧摆",
    6: "食指指根",
    7: "食指指中",
    8: "食指指尖",
    9: "中指侧摆",
    10: "中指指根",
    11: "中指指中",
    12: "中指指尖",
    13: "无名指侧摆",
    14: "无名指指根",
    15: "无名指指中",
    16: "无名指指尖",
    17: "小指侧摆",
    18: "小指指根",
    19: "小指指中",
    20: "小指指尖",
}

JOINT_NAME_TO_INDEX = {name: i for i, name in enumerate(JOINT_NAMES)}
JOINT_INDEX_TO_NAME = {i: name for i, name in enumerate(JOINT_NAMES)}

def joints_to_dict(values):
    """长度 21 的序列 → {英文名: 值}。"""
    if len(values) != JOINT_COUNT:
        raise ValueError(f"values must be length {JOINT_COUNT}, got {len(values)}")
    return {JOINT_NAMES[i]: values[i] for i in range(JOINT_COUNT)}

def dict_to_joints(named, *, missing=0.0):
    """{英文名或下标: 值} → 长度 21 的 list；缺省填 missing。"""
    out = [missing] * JOINT_COUNT
    for key, val in named.items():
        if isinstance(key, int):
            idx = key
        else:
            idx = JOINT_NAME_TO_INDEX[str(key)]
        if idx < 0 or idx >= JOINT_COUNT:
            raise IndexError(f"joint index out of range: {idx}")
        out[idx] = val
    return out

CMD_VERSION = 0x01 #查版本 / 左右手
CMD_ANGLE = 0x03 #查关节角（float）
CMD_FORCE = 0x04 # 施加力反馈。发 5 指力
CMD_ANGLE_COMPRESSED = 0x05 #查关节角（压缩）（uint）

COMPRESSED_MIN_VERSION = (2, 1, 5)

VERSION_QUERY_WAIT = 0.15          # 等版本回包
VERSION_QUERY_RETRY_COUNT = 10
ANGLE_QUERY_PERIOD_SEC = 1.0 / 30.0  # 角度查询周期
JOINT_DATA_TIMEOUT_SEC = 0.5         # 超过此时间无有效角度则视为数据过期

DEFAULT_BAUDRATES = [2000000, 460800, 1000000, 921600]
