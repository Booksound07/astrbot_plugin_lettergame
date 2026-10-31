def parse_preset_lines(lines):
    result = []
    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("（装饰行）"):
            # 装饰行
            text = line[len("（装饰行）"):].strip()
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