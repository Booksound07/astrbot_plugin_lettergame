import re
import unicodedata

from pypinyin import lazy_pinyin, Style
from pykakasi import kakasi


_kks = kakasi()

# 看着像空格、其实不是半角空格的字符：Unicode 空格分隔符(Zs) + 零宽空格
_EXTRA_BLANKS = {"\u200b"}


def is_blank(ch: str) -> bool:
    """是否“看着像空格”的字符（NBSP、全角空格、零宽空格等）。"""
    if ch == " ":
        return True
    return ch in _EXTRA_BLANKS or unicodedata.category(ch) == "Zs"


def normalize_spaces(text: str) -> str:
    """把所有“看着像空格”的字符统一成半角空格（不动大小写）。"""
    return "".join(" " if (c != " " and is_blank(c)) else c for c in text)


def normalize_search(text):

    return (
        normalize_spaces(text).lower()
        .strip()
        .replace("～", "~")
        .replace("−", "-")
        .replace("，", ",")
        .replace("（", "(")
        .replace("）", ")")
    )

def get_initial(char: str) -> str:

    #
    # 英文
    #
    if re.match(
        r"[A-Za-z]",
        char
    ):
        return char.lower()

    #
    # 汉字
    #
    if "\u4e00" <= char <= "\u9fff":

        result = lazy_pinyin(
            char,
            style=Style.FIRST_LETTER
        )

        if result:
            return result[0]

    #
    # 日文
    try:

        result = _kks.convert(
            char
        )

        if result:

            roma = result[0]["hepburn"]

            if roma:
                return roma[0].lower()

    except Exception:
        pass

    #
    # 其它字符
    #
    return ""

def is_revealed(char: str, open_chars: list[str]) -> bool:
    """
    判断一个字符是否应该被揭开：
    1. 本身字符被开出
    2. 汉字拼音首字母被开出
    3. 日文罗马音首字母被开出
    """

    opened = {
        x.lower()
        for x in open_chars
    }

    # 空格直接显示
    if is_blank(char):
        return True

    # 本身字符
    if char.lower() in opened:
        return True

    # 拼音 / 罗马音首字母
    initial = get_initial(char)

    if initial and initial in opened:
        return True

    return False