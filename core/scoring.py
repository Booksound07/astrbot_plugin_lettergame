# core/scoring.py
import time
from typing import Dict

# ==================== 计分常量（可调参数） ====================
BASE_SCORE = 980                 # 基础分（不含连击分）
COMBO_BONUS = 20                 # 连击分
FAST_PENALTY_STEP = 200          # 过快惩罚每次扣减基础分
MIN_BASE_AFTER_PENALTY = 200     # 基础分下限
PARTICIPATION_BONUS = 100        # 积极参与每次奖励
TIME_BONUS_FAST = 1.5            # 时间倍率 - 快速（≤20min）
TIME_BONUS_NORMAL = 1.0          # 时间倍率 - 正常（20-40min）
TIME_BONUS_SLOW = 0.5            # 时间倍率 - 慢速（>40min）
MAX_HOTNESS = 3.0                # 热度分上限
MIN_HOTNESS = 0.5                # 热度分下限
HOTNESS_STEP = 0.5               # 每次正确增加热度
HOTNESS_DECAY_RATE = 0.5         # 错误时热度衰减比例
PARTICIPATION_INTERVAL = 300     # 积极参与间隔阈值（秒）
FAST_INTERVAL = 5                # 过快惩罚间隔阈值（秒）
FAST_TRIGGER_COUNT = 3           # 触发过快惩罚的连续次数
# ================================================================


def get_time_multiplier(elapsed_seconds: float) -> float:
    """时间倍率分段函数"""
    if elapsed_seconds <= 1200:
        return TIME_BONUS_FAST
    elif elapsed_seconds <= 2400:
        return TIME_BONUS_FAST - (elapsed_seconds - 1200) / 2400
    else:
        return max(TIME_BONUS_SLOW, 1.0 - (elapsed_seconds - 2400) / 3600)


def get_difficulty_multiplier(question: dict, format_code_counts: dict, preset_mode: bool) -> float:
    """计算小题难度倍率"""
    if preset_mode:
        title = question["entry"]["title"]
        space_count = title.count(' ')
        multiplier = max(0.2, 3.0 - space_count * 0.45)
        return max(0.2, multiplier)
    else:
        format_code = question["entry"].get("format_code", "")
        if not format_code:
            return 1.0
        count = format_code_counts.get(format_code, 1)
        multiplier = min(3.0, 0.2 + ((count - 1) ** 0.5) * 0.40)
        return max(0.2, multiplier)


def get_opened_letters_multiplier(total_opened: int) -> float:
    """已开字母数倍率：n = 1/(m+1) + 0.8"""
    return 1.0 / (total_opened + 1) + 0.8


def get_question_opened_multiplier(revealed_count: int, title: str) -> float:
    """小题已开字母数倍率：n = 1/m - 1，其中 m = 已揭开占比（按非空格字符算）"""
    total_len = sum(1 for c in title if c != ' ')
    if total_len == 0:
        return 1.0
    ratio = revealed_count / total_len
    if ratio == 1.0:
        return 0.0
    if ratio == 0:
        return 1.0
    return max(0.0, 1.0 / ratio - 1.0)

def calculate_single_score(
    combo_refreshed: bool,
    difficulty_multiplier: float,
    opened_letters_multiplier: float,
    question_opened_multiplier: float,
    time_multiplier: float,
    hotness: float,
    fast_penalty_level: int,
    participation_count: int,
    tip_count: int
) -> tuple[float, dict]:
    # 只有刷新历史最大连击时才给连击分
    has_combo_bonus = combo_refreshed

    base = 980
    if has_combo_bonus:
        base += 20

    if fast_penalty_level >= 1:
        penalty = fast_penalty_level * FAST_PENALTY_STEP
        base = max(MIN_BASE_AFTER_PENALTY, base - penalty)

    multiplied = (
        base
        * difficulty_multiplier
        * opened_letters_multiplier
        * question_opened_multiplier
        * time_multiplier
        * hotness
    )

    bonus = PARTICIPATION_BONUS if participation_count >= 3 else 0
    multiplied += bonus

    # ===== 应用 tip 惩罚 =====
    tip_multiplier = 0.95 ** tip_count
    final_score = multiplied * tip_multiplier

    details = {
        "base_score": 980,
        "combo_bonus": 20 if has_combo_bonus else 0,
        "final_score": final_score,
        "tip_penalty": tip_multiplier
    }
    return final_score, details

def calculate_all_scores(players: Dict) -> Dict[str, int]:
    """
    计算所有玩家的总分，应用多人补正。
    """
    result = {}
    # 统计参与人数：有答题记录的玩家
    participant_count = 0
    for uid, data in players.items():
        if data.get("answers"):
            participant_count += 1
    participant_count = max(1, participant_count)

    for uid, data in players.items():
        total = 0
        for ans in data.get("answers", []):
            detail = ans.get("score_detail", {})
            total += detail.get("final_score", 0)
        # 多人补正：乘以参与人数
        total *= participant_count
        result[uid] = int(round(total))

    return result