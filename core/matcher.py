import unicodedata
from difflib import SequenceMatcher

_EXTRA_BLANKS = {"\u200b"}


def _is_blank(ch: str) -> bool:
    return ch == " " or ch in _EXTRA_BLANKS or unicodedata.category(ch) == "Zs"


def _norm_spaces(text: str) -> str:
    return "".join(" " if (c != " " and _is_blank(c)) else c for c in text)


def normalize(text: str) -> str:
       return (
        _norm_spaces(text).strip()
        .lower()
        .replace("～", "~")
        .replace("−", "-")
        .replace("，", ",")
    )
    
def match_answer(
    answer: str,
    candidates: list[str]
) -> bool:

    ans = normalize(answer)

    return any(
        ans == normalize(x)
        for x in candidates
    )

def calculate_similarity(text1: str, text2: str) -> float:
    """计算两个字符串的字符相似度，返回 0~100"""
    text1 = _norm_spaces(text1).strip().lower()
    text2 = _norm_spaces(text2).strip().lower()

    if not text1 or not text2:
        return 0.0

    return SequenceMatcher(
        None,
        text1,
        text2
    ).ratio() * 100

def strip_trailing_brackets(text: str) -> str:
    """只剥掉结尾那一段成对括号（含前面的空格），全角半角都算。
    名字中间的括号、整名就是括号的，一律不动。"""
    s = _norm_spaces(str(text)).strip()
    if not s or s[-1] not in ")）":
        return s
    depth = 0
    idx = -1
    for i in range(len(s) - 1, -1, -1):
        ch = s[i]
        if ch in ")）":
            depth += 1
        elif ch in "(（":
            depth -= 1
            if depth == 0:
                idx = i
                break
    if idx <= 0:
        return s
    return s[:idx].rstrip()
