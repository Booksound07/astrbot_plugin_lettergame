from .matcher import normalize_spaces


def parse_text(text: str) -> list:
    """解析纯文本，每行一个题目，全部默认为标准曲名，忽略空行"""
    lines = text.strip().splitlines()
    songs = []
    for line in lines:
        title = normalize_spaces(line)
        if title:
            songs.append({"title": title, "is_standard": True})
    return songs