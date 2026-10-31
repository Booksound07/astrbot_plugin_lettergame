from pathlib import Path
import json
import os
import tempfile

DATA_DIR = (
    Path.home()
    / ".astrbot"
    / "data"
    / "plugin_data"
    / "astrbot_plugin_lettergame"
)

COMPETITION_FILE = DATA_DIR / "competition_settings.json"


def load_competition_settings():
    if not COMPETITION_FILE.exists():
        return {}

    try:
        with open(COMPETITION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {}

        return data

    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            f"[开字母] 读取比赛模式设置失败：{e}"
        )
        return {}


def save_competition_settings(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 先写入临时文件，写完整后再替换正式文件
    fd, temp_path = tempfile.mkstemp(
        dir=DATA_DIR,
        prefix="competition_settings_",
        suffix=".tmp"
    )

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )
            f.flush()
            os.fsync(f.fileno())

        # 写入完成后，再替换正式文件
        os.replace(
            temp_path,
            COMPETITION_FILE
        )

    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def get_competition_state(group_id):
    data = load_competition_settings()

    return data.get(
        str(group_id),
        {
            "enabled": False,
            "once": False
        }
    )


def set_competition_state(
    group_id,
    enabled=None,
    once=None
):
    data = load_competition_settings()

    key = str(group_id)

    if key not in data:
        data[key] = {
            "enabled": False,
            "once": False
        }

    if enabled is not None:
        data[key]["enabled"] = enabled

    if once is not None:
        data[key]["once"] = once

    save_competition_settings(data)


def consume_competition_once(group_id):
    data = load_competition_settings()

    key = str(group_id)

    if key not in data:
        return False

    once = data[key].get("once", False)

    data[key]["once"] = False

    save_competition_settings(data)

    return once