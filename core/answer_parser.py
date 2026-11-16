"""作答序号解析（2026-11-16 定案：必须严格「数字 空格 正文」）

规则：
1. 分隔符只能是空格，可以是多个；数字后不跟空格的一律不算作答；
2. 空格之后的一切都算正文，包括数字（所以「1 996」是第1题答 996）；
3. 只发数字、只发「数字+空格」，都不算作答，静默；
4. 前导零、0、越界、装饰行号，统一按序号错误；
5. 多行作答不判定对错，只提示一次只能答一题，不改连击。

NBSP、全角空格、制表符在解析前统一换成半角空格。
"""

import re

from .utils import normalize_spaces

# normalize_spaces 只认 Unicode 空格类，制表符和纵向空白得自己换
_TAB_CHARS = ("\t", "\u000b", "\u000c", "\r")

# 只把全角数字折成半角，正文里的字母符号一律不动
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

# 数字 + 一个以上空格 + 非空正文
NUMBER_RE = re.compile(r"^([0-9]+)( +)(\S.*)$")

# 一行是不是「数字 空格 正文」
NUMBER_LINE_RE = re.compile(r"^\s*[0-9]+ +\S")

STATUS_OK = "ok"
STATUS_NO_NUMBER = "no_number"
STATUS_NO_CONTENT = "no_content"
STATUS_BAD_NUMBER = "bad_number"
STATUS_MULTI = "multi"


def pre_normalize(text: str) -> str:
    """解析前统一空白字符"""
    t = str(text or "").translate(_FULLWIDTH_DIGITS)
    for ch in _TAB_CHARS:
        t = t.replace(ch, " ")
    return normalize_spaces(t)


def looks_like_numbered_line(text: str) -> bool:
    return NUMBER_LINE_RE.match(pre_normalize(text).strip()) is not None


def parse_numbered_answer(text: str, total_questions: int):
    """解析一条作答消息，返回 (status, number, content)

    status:
      "ok"         正常作答
      "no_number"  不是「数字 空格 正文」形式，不算作答
      "no_content" 只发了数字或数字加空格，不算作答
      "bad_number" 序号非法（前导零、0、越界），按序号错误
      "multi"      多行作答，不判定对错，也不改连击
    """
    s = pre_normalize(text).strip()

    if not s:
        return STATUS_NO_NUMBER, None, ""

    lines = [line.strip() for line in s.split("\n") if line.strip()]

    # 多行作答：两行以上「数字 空格 正文」直接判错
    if sum(1 for line in lines if NUMBER_LINE_RE.match(line)) >= 2:
        return STATUS_MULTI, None, s

    # 其余情况只看第一行，后面的内容不参与判定
    s = lines[0] if lines else ""

    match = NUMBER_RE.match(s)

    if not match:
        # 只有数字，或者数字后面全是空格
        if re.fullmatch(r"[0-9]+ *", s):
            return STATUS_NO_CONTENT, None, ""
        return STATUS_NO_NUMBER, None, ""

    raw_number = match.group(1)
    content = match.group(3).strip()

    if not content:
        return STATUS_NO_CONTENT, None, ""

    # 前导零不认
    if len(raw_number) > 1 and raw_number.startswith("0"):
        return STATUS_BAD_NUMBER, None, content

    # 超长数字直接按序号错误处理，别丢给 int()
    if len(raw_number) > 6:
        return STATUS_BAD_NUMBER, None, content

    number = int(raw_number)

    if number < 1:
        return STATUS_BAD_NUMBER, None, content

    if total_questions and number > total_questions:
        return STATUS_BAD_NUMBER, None, content

    return STATUS_OK, number, content
