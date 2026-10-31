import json
from pathlib import Path

PLUGIN_DATA_DIR = Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_lettergame"
CACHE_DIR = PLUGIN_DATA_DIR / "cache" / "user_name_cache"
CACHE_FILE = CACHE_DIR / "names.json"

def _ensure_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _load_cache() -> dict:
    _ensure_dir()
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def _save_cache(cache: dict):
    _ensure_dir()
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def update_user_name(user_id: str, new_name: str):
    """更新用户昵称（如果最新昵称不同则追加）"""
    cache = _load_cache()
    if user_id not in cache:
        cache[user_id] = []
    if not cache[user_id] or cache[user_id][-1] != new_name:
        cache[user_id].append(new_name)
        _save_cache(cache)

def get_latest_name(user_id: str) -> str | None:
    """获取用户最新昵称，若无则返回 None"""
    cache = _load_cache()
    if user_id in cache and cache[user_id]:
        return cache[user_id][-1]
    return None