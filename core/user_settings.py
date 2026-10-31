from pathlib import Path
import json
from typing import List

DATA_DIR = Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_lettergame"
USER_SETTINGS_DIR = DATA_DIR / "user_settings"

USER_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

def get_user_settings_file(user_id: str) -> Path:
    return USER_SETTINGS_DIR / f"{user_id}.json"

def load_user_settings(user_id: str) -> dict:
    file_path = get_user_settings_file(user_id)
    if not file_path.exists():
        return {"disabled_banks": []}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"disabled_banks": []}

def save_user_settings(user_id: str, settings: dict):
    file_path = get_user_settings_file(user_id)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

def disable_bank(user_id: str, bank_name: str) -> bool:
    settings = load_user_settings(user_id)
    bank_name = bank_name.lower()
    if bank_name in settings["disabled_banks"]:
        return False
    settings["disabled_banks"].append(bank_name)
    save_user_settings(user_id, settings)
    return True

def enable_bank(user_id: str, bank_name: str) -> bool:
    settings = load_user_settings(user_id)
    bank_name = bank_name.lower()
    if bank_name not in settings["disabled_banks"]:
        return False
    settings["disabled_banks"].remove(bank_name)
    save_user_settings(user_id, settings)
    return True

def get_disabled_banks(user_id: str) -> list:
    settings = load_user_settings(user_id)
    return settings.get("disabled_banks", [])

def is_bank_disabled(user_id: str, bank_name: str) -> bool:
    return bank_name.lower() in get_disabled_banks(user_id)

# ==================== 自定义题库禁用/启用 ====================

def disable_custom_bank(user_id: str, bank_id: int) -> bool:
    """禁用自定义题库"""
    settings = load_user_settings(user_id)
    if "disabled_custom_banks" not in settings:
        settings["disabled_custom_banks"] = []
    if bank_id in settings["disabled_custom_banks"]:
        return False
    settings["disabled_custom_banks"].append(bank_id)
    save_user_settings(user_id, settings)
    return True

def enable_custom_bank(user_id: str, bank_id: int) -> bool:
    """启用自定义题库"""
    settings = load_user_settings(user_id)
    if "disabled_custom_banks" not in settings:
        return False
    if bank_id not in settings["disabled_custom_banks"]:
        return False
    settings["disabled_custom_banks"].remove(bank_id)
    save_user_settings(user_id, settings)
    return True

def get_disabled_custom_banks(user_id: str) -> list:
    """获取已禁用的自定义题库ID列表"""
    settings = load_user_settings(user_id)
    return settings.get("disabled_custom_banks", [])

def is_custom_bank_disabled(user_id: str, bank_id: int) -> bool:
    """检查自定义题库是否被禁用"""
    return bank_id in get_disabled_custom_banks(user_id)

# ==================== 查询模式 ====================
# 0: 默认模式（严格逐字符匹配，*排除已开字母）
# 1: 无视空格模式（匹配前删除所有空格）
# 2: 空格=*模式（空格和*都匹配任意字符）
# 3: 无视已开字母模式（*匹配所有字符，不排除已开字母）

def get_query_mode(user_id: str) -> int:
    """获取用户的查询模式，默认为0"""
    settings = load_user_settings(user_id)
    return settings.get("query_mode", 0)

def set_query_mode(user_id: str, mode: int) -> bool:
    """设置用户的查询模式，返回是否成功"""
    if mode not in [0, 1, 2, 3]:
        return False
    settings = load_user_settings(user_id)
    settings["query_mode"] = mode
    save_user_settings(user_id, settings)
    return True