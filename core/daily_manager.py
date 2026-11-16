import json
import os
from pathlib import Path

DATA_DIR = (
    Path.home()
    / ".astrbot"
    / "data"
    / "plugin_data"
    / "astrbot_plugin_lettergame"
)

DAILY_FILE = DATA_DIR / "daily_record.json"

daily_record = {}

# ===== 说明 =====
# daily_record 是模块级全局字典，load_daily_record() 会把它重新绑定成新对象。
# 所以外部千万不要 `from .daily_manager import daily_record` 之后再改这个字典，
# 那样改的只是导入那一刻的旧对象，既查不到落盘数据，也写不进文件
# （每日挑战就会变成每个群能无限重复开）。
# 统一走下面两个函数读写，或者 `from .core import daily_manager` 再用
# daily_manager.daily_record。


def _daily_key(group_id, bank: str) -> str:
    return f"{group_id}_{bank}"


def get_daily_record(group_id, bank: str) -> str:
    """查询某群某题库的每日挑战记录日期，没有则返回空串。"""
    return daily_record.get(_daily_key(group_id, bank), "")


def set_daily_record(group_id, bank: str, date_str: str):
    """写入某群某题库的每日挑战记录日期（只改内存，需再调 save_daily_record）。"""
    daily_record[_daily_key(group_id, bank)] = date_str


def load_daily_record():

    global daily_record

    if not DAILY_FILE.exists():

        daily_record = {}

        return

    try:

        with open(
            DAILY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        daily_record = data if isinstance(data, dict) else {}

    except Exception:

        daily_record = {}


def save_daily_record():

    try:

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        tmp_file = DAILY_FILE.with_suffix(".json.tmp")

        with open(
            tmp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                daily_record,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(tmp_file, DAILY_FILE)

    except Exception:
        # 落盘失败不要打断开题流程
        pass
