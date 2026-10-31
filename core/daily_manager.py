import json
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

            daily_record = json.load(f)

    except:

        daily_record = {}


def save_daily_record():

    with open(
        DAILY_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            daily_record,
            f,
            ensure_ascii=False,
            indent=2
        )