import re

def parse_preset_text(text):
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # 检测装饰行：+序号. 内容 或 +序号、内容
        decor_match = re.match(r'^\+[0-9０-９]+\s*[\.．、]\s*(.*)', line)
        if decor_match:
            # 存储为 （装饰行）内容
            lines.append('（装饰行）' + decor_match.group(1).strip())
            continue

        # 普通题目：去掉序号
        normal_match = re.sub(r'^[0-9０-９]+\s*[\.．、]\s*', '', line)
        if normal_match:
            lines.append(normal_match)

    return lines