from .matcher import normalize_spaces


def parse_preset_lines(lines):
    result = []
    for line in lines:
        line = normalize_spaces(line)
        if not line:
            continue

        if line.startswith("（装饰行）"):
            # 装饰行
            text = normalize_spaces(line[len("（装饰行）"):])
            result.append({
                "type": "decor",
                "text": text
            })
        else:
            # 普通题目
            result.append({
                "type": "question",
                "entry": {"title": line},
                "mask": "".join(" " if c.isspace() else "*" for c in line),
                "solved": False
            })
    return result