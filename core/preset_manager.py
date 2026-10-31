from pathlib import Path
import json
import time

from .user_name_cache import update_user_name

PLUGIN_DATA_DIR = (
    Path.home()
    / ".astrbot"
    / "data"
    / "plugin_data"
    / "astrbot_plugin_lettergame"
)

PRESET_DIR = (
    PLUGIN_DATA_DIR
    / "presets"
)

PRESET_DIR.mkdir(
    parents=True,
    exist_ok=True
)

META_FILE = (
    PRESET_DIR
    / "meta.json"
)

MAX_PRESETS = 100000


def load_meta():

    if not META_FILE.exists():

        data = {
            "next_id": 1,
            "ids": []
        }

        with open(
            META_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        return data

    with open(
        META_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


def save_meta(data):

    with open(
        META_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


def add_preset(
    lines,
    uploader=""
):

    meta = load_meta()

    preset_id = meta["next_id"]

    item = {
        "id": preset_id,
        "time": int(time.time()),
        "uploader": uploader,

        # [] = 所有群可开
        "allowed_groups": [],

        # [] = 仅作者可开
        "allowed_users": [],

        "lines": lines
    }

    preset_file = (
        PRESET_DIR
        / f"{preset_id}.json"
    )

    with open(
        preset_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            item,
            f,
            ensure_ascii=False,
            indent=2
        )

    meta["ids"].append(
        preset_id
    )

    meta["next_id"] += 1

    while len(meta["ids"]) > MAX_PRESETS:

        oldest_id = meta["ids"].pop(0)

        old_file = (
            PRESET_DIR
            / f"{oldest_id}.json"
        )

        if old_file.exists():

            old_file.unlink()

    save_meta(meta)

    return preset_id


def get_preset(
    preset_id
):

    preset_file = (
        PRESET_DIR
        / f"{preset_id}.json"
    )

    if not preset_file.exists():

        return None

    with open(
        preset_file,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)
    
    # 兼容旧版本
    if "allowed_groups" not in item:
        item["allowed_groups"] = []

    if "allowed_users" not in item:
        item["allowed_users"] = []

    if "uploader" not in item:
        item["uploader"] = ""


def save_preset(
    item
):

    preset_id = item["id"]

    preset_file = (
        PRESET_DIR
        / f"{preset_id}.json"
    )

    with open(
        preset_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            item,
            f,
            ensure_ascii=False,
            indent=4
        )
        
def delete_preset(
    preset_id
):

    preset_file = (
        PRESET_DIR
        / f"{preset_id}.json"
    )

    if not preset_file.exists():

        return False

    preset_file.unlink()

    return True

def get_user_presets(
    user_id
):

    result = []

    for preset_file in PRESET_DIR.glob(
        "*.json"
    ):

        if (
            preset_file.name
            ==
            "meta.json"
        ):
            continue

        with open(
            preset_file,
            "r",
            encoding="utf-8"
        ) as f:

            item = json.load(
                f
            )

        if (
            item.get(
                "uploader"
            )
            ==
            user_id
        ):

            result.append(
                item
            )

    result.sort(
        key=lambda x: x["id"]
    )

    return result

def preview_preset(item):
    result = []
    count = 0
    for i, line in enumerate(item["lines"], start=1):
        if line.startswith("（装饰行）"):
            # 装饰行：显示内容，不带前缀
            text = line[len("（装饰行）"):].strip()
            result.append(f"{i}. {text}")
            continue

        # 普通题目
        mask = ""
        for ch in line:
            if ch.isspace():
                mask += " "
            else:
                mask += "*"
        result.append(f"{i}. {mask}")
        count += 1
    return result, count

def get_preset_leaderboard(preset_id: int) -> dict:
    """获取预设排行榜数据，返回 {group_id: {user_id: score}}"""
    preset = get_preset(preset_id)
    if preset is None:
        return {}
    return preset.get("leaderboard", {})

def update_preset_leaderboard(
    preset_id: int,
    group_id: str,
    user_id: str,
    score: int,
    user_name: str = ""
) -> bool:
    """
    更新预设排行榜，返回 True 表示首次记录成功，False 表示已存在记录
    """
    if user_name:
        update_user_name(user_id, user_name)
    
    preset = get_preset(preset_id)
    if preset is None:
        return False
    
    if "leaderboard" not in preset:
        preset["leaderboard"] = {}
    
    if group_id not in preset["leaderboard"]:
        preset["leaderboard"][group_id] = {}
    
    if user_id in preset["leaderboard"][group_id]:
        return False  # 已经记录过了
    
    preset["leaderboard"][group_id][user_id] = score
    save_preset(preset)
    return True