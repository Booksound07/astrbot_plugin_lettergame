# core/daily_scoring.py
# 每日挑战难度评分

def is_cjk(ch):
    code = ord(ch)
    if 0x4E00 <= code <= 0x9FFF:
        return True
    if 0x3400 <= code <= 0x4DBF:
        return True
    if 0x20000 <= code <= 0x2A6DF:
        return True
    if 0x3040 <= code <= 0x309F:
        return True
    if 0x30A0 <= code <= 0x30FF:
        return True
    if 0xFF65 <= code <= 0xFF9F:
        return True
    return False


def is_ascii_punct(ch):
    code = ord(ch)
    if code > 127:
        return False
    return not ch.isalnum()


def is_fullwidth_ascii(ch):
    code = ord(ch)
    return 0xFF01 <= code <= 0xFF5E


def is_english_letter(ch):
    return ch.isascii() and ch.isalpha()


def is_digit(ch):
    return ch.isdigit()


def score_format_code(count):
    if count <= 1:
        return 1.0
    return float(min(count, 20))


def score_spaces(title):
    spaces = title.count(" ")
    return float(max(0, 5 - spaces))


def score_aliases(alias_count):
    if alias_count <= 1:
        return 7.0
    return max(0.0, 7.0 - 0.5 * (alias_count - 1))


def score_characters(title):
    chars = [c for c in title if c != " "]
    if not chars:
        return 0.0
    total = 0.0
    a = b = c = eng = 0
    for ch in chars:
        if is_english_letter(ch):
            eng += 1
        elif is_cjk(ch) or is_digit(ch):
            a += 1
            total += 0.5
        elif is_ascii_punct(ch) or is_fullwidth_ascii(ch):
            b += 1
            total += 1.0
        else:
            c += 1
            total += 1.5
    if eng == 0:
        if a == len(chars):
            total += 1.0
        elif b == len(chars):
            total += 1.5
        elif c == len(chars):
            total += 2.0
    return total


def calc_one(title, alias_count, format_code_count):
    s1 = score_format_code(format_code_count)
    s2 = score_spaces(title)
    s3 = score_aliases(alias_count)
    s4 = score_characters(title)
    return s1 + s2 + s3 + s4, {
        "format_code": s1,
        "spaces": s2,
        "aliases": s3,
        "chars": s4,
    }


def calc_daily_total(puzzles, snapshot, get_aliases_func):
    """
    puzzles: 本局题目列表，每个元素是 {"entry": {...}, ...}
    snapshot: {format_code: count} 格式码快照
    get_aliases_func: 输入 song dict，返回别名列表
    """
    total = 0.0
    breakdown = []
    for q in puzzles:
        entry = q["entry"]
        title = entry.get("title", "")
        fc = entry.get("format_code", "")
        fc_count = snapshot.get(fc, 1)
        alias_list = get_aliases_func(entry)
        alias_count = len(alias_list) if alias_list else 0
        score, detail = calc_one(title, alias_count, fc_count)
        total += score
        breakdown.append({
            "title": title,
            "score": score,
            "detail": detail,
        })
    return total, breakdown


def estimate_daily_limit(total_score):
    """
    按新中位 275 等比缩放后的阈值
    原阈值：100/120/150/180/210
    新阈值：180/220/280/330/390
    """
    if total_score <= 180:
        return 5
    if total_score <= 220:
        return 7
    if total_score <= 280:
        return 8
    if total_score <= 330:
        return 10
    if total_score <= 390:
        return 11
    return 13