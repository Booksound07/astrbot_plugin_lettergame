import re


def parse_query(query: str):
    """
    返回：
        ("format", 格式码)
        ("mask", 原始mask)
        (None, None)
    """

    query = query.strip()

    # ---------- 格式码 ----------
    if re.fullmatch(r"\d+(?:-\d+)*", query):
        return "format", query

    # ---------- Mask ----------
    if "*" in query:
        return "mask", query

    return None, None