import json
import random
from pathlib import Path
from .scoring import (
    MAX_HOTNESS,
    MIN_HOTNESS,
    HOTNESS_STEP,
    HOTNESS_DECAY_RATE,
    FAST_INTERVAL,
    FAST_TRIGGER_COUNT
)

PLUGIN_DATA_DIR = Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_lettergame"
PLUGIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = PLUGIN_DATA_DIR / "game_state.json"

class GameManager:
    def __init__(self):
        self.load()

    def load(self):
        if STATE_FILE.exists():
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                self.state = json.load(f)
        else:
            self.state = {}

    def save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False)

    def new_game(self, group_id: str, questions: list, preset_id: int = None):
        self.state[group_id] = {
            "questions": questions,
            "open_chars": [],
            "open_limit": None,
            "competition_mode": False,
            "players": {},
            "first_open_time": None,
            "preset_id": preset_id,
            "tip_count": 0,
            "daily_limit": None,
            "daily_expire_at": None,
            "daily_snapshot": {},
        }
        self.save()

    # ===== 获取tip次数 =====
    def get_tip_count(self, group_id: str) -> int:
        return self.state.get(group_id, {}).get("tip_count", 0)

    # ===== 增加tip次数 =====
    def increment_tip_count(self, group_id: str):
        if group_id in self.state:
            self.state[group_id]["tip_count"] = self.state[group_id].get("tip_count", 0) + 1
            self.save()

    # ===== 获取每日挑战限开数 =====
    def get_daily_limit(self, group_id: str) -> int:
        return self.state.get(group_id, {}).get("daily_limit", 0)

    # ===== 获取每日挑战过期时间 =====
    def get_daily_expire_at(self, group_id: str) -> int:
        return self.state.get(group_id, {}).get("daily_expire_at", 0)

    # ===== 获取格式码快照 =====
    def get_daily_snapshot(self, group_id: str) -> dict:
        return self.state.get(group_id, {}).get("daily_snapshot", {})


    def get_state(self, group_id: str):
        return self.state.get(group_id, None)

    def end_game(self, group_id: str):
        if group_id in self.state:
            self.state.pop(group_id)
            self.save()
            
    def set_competition_mode(self, group_id: str, enabled: bool):
        """开启或关闭比赛模式"""
        if group_id not in self.state:
            return
        self.state[group_id]["competition_mode"] = enabled
        if enabled:
            self.state[group_id]["players"] = {}
            self.state[group_id]["first_open_time"] = None
        self.save()

    def is_competition_mode(self, group_id):
        return self.state.get(group_id, {}).get("competition_mode", False)

    def get_first_open_time(self, group_id):
        return self.state.get(group_id, {}).get("first_open_time")

    def set_first_open_time(self, group_id, time_val):
        if group_id in self.state:
            self.state[group_id]["first_open_time"] = time_val
            self.save()

    def record_answer(
        self,
        group_id: str,
        user_id: str,
        user_name: str,
        question_idx: int,
        elapsed: float,
        opened_letters: int,
        timestamp: float,
        score_detail: dict
    ):
        if not self.is_competition_mode(group_id):
            return
        if group_id not in self.state:
            return
        players = self.state[group_id].setdefault("players", {})
        if user_id not in players:
            players[user_id] = {"name": user_name, "answers": []}
        # 保留已有状态，避免覆盖
        if not players[user_id].get("answers"):
            players[user_id]["name"] = user_name
        players[user_id]["answers"].append({
            "question_idx": question_idx,
            "elapsed": elapsed,
            "opened_letters": opened_letters,
            "timestamp": timestamp,
            "score_detail": score_detail
        })
        self.save()

    def get_players(self, group_id):
        return self.state.get(group_id, {}).get("players", {})
    
    def get_preset_id(self, group_id):
        return self.state.get(group_id, {}).get("preset_id")

    def init_player_state(self, group_id: str, user_id: str):
        """初始化玩家的计分状态"""
        if group_id not in self.state:
            return
        players = self.state[group_id].setdefault("players", {})
        if user_id not in players:
            players[user_id] = {
                "name": "",
                "answers": [],
                "hotness": 1.0,
                "current_combo": 0,
                "max_combo": 0,
                "last_answer_time": 0,
                "fast_count": 0,
                "fast_penalty_level": 0,
                "participation_count": 0,
                "combo_refreshed": False
            }
            self.save()

    def update_player_state(
        self,
        group_id: str,
        user_id: str,
        is_correct: bool,
        timestamp: float
    ) -> dict:
        """
        更新玩家状态，返回更新后的状态字典
        包含：热度分、连击分、过快惩罚、积极参与奖励
        """
        if group_id not in self.state:
            return {}
        players = self.state[group_id].setdefault("players", {})
        if user_id not in players:
            self.init_player_state(group_id, user_id)
        
        state = players[user_id]
        
        if is_correct:
            # ===== 热度分：正确 +HOTNESS_STEP，上限 MAX_HOTNESS =====
            state["hotness"] = min(MAX_HOTNESS, state["hotness"] + HOTNESS_STEP)
            
            # ===== 连击分：连击数 +1，只有超过历史最大才算刷新 =====
            old_max_combo = state["max_combo"]
            state["current_combo"] += 1
            if state["current_combo"] > state["max_combo"]:
                state["max_combo"] = state["current_combo"]
            state["combo_refreshed"] = state["current_combo"] > old_max_combo
            
            # ===== 过快惩罚：连续 FAST_TRIGGER_COUNT 次间隔小于 FAST_INTERVAL 秒触发 =====
            if state["last_answer_time"] > 0:
                interval = timestamp - state["last_answer_time"]
                if interval < FAST_INTERVAL:
                    state["fast_count"] += 1
                    if state["fast_count"] >= FAST_TRIGGER_COUNT:
                        state["fast_penalty_level"] += 1
                else:
                    state["fast_count"] = 0
            
            # ===== 积极参与：间隔≤5分钟连续计数 =====
            if state["last_answer_time"] > 0:
                interval = timestamp - state["last_answer_time"]
                if interval <= 300:
                    state["participation_count"] += 1
                else:
                    state["participation_count"] = 1
            else:
                state["participation_count"] = 1
            
            state["last_answer_time"] = timestamp
            
        else:
            # ===== 错误：热度减半，连击归零 =====
            state["hotness"] = max(MIN_HOTNESS, state["hotness"] * HOTNESS_DECAY_RATE)
            state["current_combo"] = 0
            state["fast_count"] = 0
            state["combo_refreshed"] = False
            
            # 错误：重置 fast_count，保留 participation_count 和 fast_penalty_level
            
        self.save()
        return state

    def get_player_state(self, group_id: str, user_id: str) -> dict:
        """获取玩家状态"""
        if group_id not in self.state:
            return {}
        players = self.state[group_id].get("players", {})
        return players.get(user_id, {})