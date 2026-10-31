from astrbot.api import logger
from pathlib import Path
import random
import time
from datetime import datetime

from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageOps,
    ImageFilter,
    ImageEnhance
)

PLUGIN_NAME = "astrbot_plugin_lettergame"

PLUGIN_DATA_DIR = (
    Path.home()
    / ".astrbot"
    / "data"
    / "plugin_data"
    / PLUGIN_NAME
)

FONT_DIR = (
    PLUGIN_DATA_DIR
    / "fonts"
)

FONT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

FONT_NAME = "NotoSansSChineseMedium.ttf"

def load_font(size):
    return ImageFont.truetype(
        str(
            FONT_DIR / FONT_NAME
        ),
        size
    )

def round_corner(
    image,
    radius=16
):
    mask = Image.new(
        "L",
        image.size,
        0
    )

    mask_draw = ImageDraw.Draw(mask)

    mask_draw.rounded_rectangle(
        (
            0,
            0,
            image.width,
            image.height
        ),
        radius=radius,
        fill=255
    )

    image = image.convert("RGBA")
    image.putalpha(mask)

    return image