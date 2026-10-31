# -*- coding: utf-8 -*-
"""
开字母速查表 xlsx -> songs.json

用法：
    把本脚本和 xlsx 放在同一个文件夹，直接运行即可，会在同目录生成 songs.json。
    不需要装任何第三方库，只用 Python 标准库。

要改的东西全在下面的「配置区」里，一般只改前三个：
    EXCEL_FILE        要读的 Excel 文件名
    JSON_FILE         生成的 json 文件名
    HEADER_ROW        表头在第几行（从 1 开始数）
                      默认 None = 自动探测，一般不用管；
                      有的表第 1 行是说明、第 2 行才是表头，自动也能认出来
    TITLE_HEADERS     曲名那一列的表头可能叫哪些名字
    STANDARD_HEADERS  是否标准那一列的表头可能叫哪些名字
    STANDARD_TRUE     哪些值算作「标准曲名」

空格处理（重点）：
    xlsx 里常见 NBSP(U+00A0)、全角空格(U+3000)、零宽空格(U+200B)，
    肉眼几乎看不出来，但会让查曲、题板、猜题判定全部对不上。
    本脚本会把所有「看着像空格」的字符统一换成半角空格 U+0020，
    并去掉首尾空白，所以导出的曲名是干净的。

注意：
    本脚本只导出「曲名」和「是否标准」两列，不处理别名。
    别名请在插件里用 /导入别名 维护，或直接改题库的 aliases.json。
"""

import json
import os
import zipfile
import unicodedata
import xml.etree.ElementTree as ET

# ======================== 配置区 ========================
EXCEL_FILE = "Rizline开字母速查表.xlsx"
JSON_FILE = "songs.json"

# 表头在第几行（从 1 开始数）。
#   None = 自动在前 MAX_HEADER_SCAN 行里找「同时有曲名列和是否标准列」的那一行
#   填数字 = 强制指定，比如写成 2 就只认第 2 行
HEADER_ROW = None
MAX_HEADER_SCAN = 5

# 曲名列的表头候选
TITLE_HEADERS = {"曲名", "title"}

# 是否标准列的表头候选
STANDARD_HEADERS = {"标准曲名", "是否是标准曲名", "is_standard"}

# 哪些值算作标准曲名
STANDARD_TRUE = {"1", "1.0", "true", "是"}
# ========================================================

# 脚本所在目录。下面写文件名时会以这里为基准，
# 所以不管从哪里启动，都能找到同目录的 Excel 和 json
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_path(path):
    """相对路径按脚本所在目录解析，绝对路径原样返回"""
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)

# 零宽类字符，肉眼完全看不到，但会让匹配对不上
ZERO_WIDTH = {"\u200b", "\ufeff"}

NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def normalize_ws(text):
    """把所有非半角空格的空白字符统一成半角空格 U+0020"""
    out = []
    for ch in text:
        if ch == " ":
            out.append(ch)
        elif unicodedata.category(ch) == "Zs" or ch in ZERO_WIDTH:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def clean(text):
    """先统一空白，再去掉首尾空白"""
    return normalize_ws(str(text)).strip()


def read_shared_strings(z):
    """读取共享字符串表（Excel 保存的 xlsx 一般走这个）"""
    try:
        data = z.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(data)
    strings = []

    for si in root.findall("a:si", NS):
        text = ""
        for node in si.iter():
            if node.tag.endswith("}t"):
                text += node.text or ""
        strings.append(text)

    return strings


def col_to_num(col):
    """把列名 A、B、AA 换成序号 1、2、27"""
    value = 0
    for ch in col:
        value = value * 26 + (ord(ch.upper()) - 64)
    return value


def read_sheet(z, shared_strings):
    """读取第一张表，返回 [ {列号: 文本}, ... ]"""
    data = z.read("xl/worksheets/sheet1.xml")
    root = ET.fromstring(data)
    rows = []

    for row in root.findall(".//a:row", NS):
        row_data = {}

        for cell in row.findall("a:c", NS):
            ref = cell.attrib.get("r", "")
            col = "".join(x for x in ref if x.isalpha())
            col_num = col_to_num(col)

            cell_type = cell.attrib.get("t")
            v = cell.find("a:v", NS)

            if v is None:
                # 内联字符串：<is><t>...</t></is>
                # openpyxl、部分在线表格导出会这么写
                inline = cell.find("a:is", NS)
                if inline is not None:
                    text = "".join(
                        t.text or "" for t in inline.iter()
                        if t.tag.endswith("}t")
                    )
                    if text:
                        row_data[col_num] = text
                continue

            if cell_type == "s":
                idx = int(v.text)
                if idx < len(shared_strings):
                    row_data[col_num] = shared_strings[idx]
            else:
                row_data[col_num] = v.text

        rows.append(row_data)

    return rows


def find_header_column(header_row, targets):
    """在表头行里找目标列，返回列号"""
    for col, value in header_row.items():
        if clean(value) in targets:
            return col
    return None


def locate_header(rows):
    """定位表头行，返回 (下标, 该行数据)；找不到返回 (None, None)"""

    if HEADER_ROW is not None:
        idx = HEADER_ROW - 1
        if idx < 0 or idx >= len(rows):
            raise ValueError(
                f"HEADER_ROW={HEADER_ROW} 超出表格范围（共 {len(rows)} 行）"
            )
        return idx, rows[idx]

    # 自动探测：前几行里，同时能看到曲名列和是否标准列的那一行就是表头
    for idx in range(min(MAX_HEADER_SCAN, len(rows))):
        row = rows[idx]
        if (
            find_header_column(row, TITLE_HEADERS) is not None
            and find_header_column(row, STANDARD_HEADERS) is not None
        ):
            return idx, row

    return None, None


def excel_to_json(excel_file=EXCEL_FILE, json_file=JSON_FILE):
    """主流程：读 xlsx，写 songs.json"""

    with zipfile.ZipFile(resolve_path(excel_file), "r") as z:
        shared_strings = read_shared_strings(z)
        rows = read_sheet(z, shared_strings)

    header_index, header_row = locate_header(rows)

    if header_row is None:
        raise ValueError(
            "没找到表头行，检查 TITLE_HEADERS、STANDARD_HEADERS，"
            "或者手动指定 HEADER_ROW（从 1 开始数）"
        )

    title_col = find_header_column(header_row, TITLE_HEADERS)
    standard_col = find_header_column(header_row, STANDARD_HEADERS)

    if title_col is None:
        raise ValueError("未找到曲名列，检查 TITLE_HEADERS")

    if standard_col is None:
        raise ValueError("未找到是否标准列，检查 STANDARD_HEADERS")

    songs = []
    standard_titles = set()
    duplicate_titles = []

    for row in rows[header_index + 1:]:

        title = clean(row.get(title_col, ""))
        if not title:
            continue

        raw_standard = clean(row.get(standard_col, "")).lower()
        is_standard = raw_standard in STANDARD_TRUE

        songs.append({
            "title": title,
            "is_standard": is_standard
        })

        if is_standard:
            key = title.lower()
            if key in standard_titles:
                duplicate_titles.append(title)
            standard_titles.add(key)

    with open(resolve_path(json_file), "w", encoding="utf-8") as f:
        json.dump(songs, f, ensure_ascii=False, indent=2)

    print(f"导出完成：{len(songs)} 首 -> {json_file}")

    if duplicate_titles:
        print("\n发现重复标准曲名（后者可能与前者冲突）：")
        for title in duplicate_titles:
            print(f"  - {title}")

    return songs


if __name__ == "__main__":
    excel_to_json(EXCEL_FILE, JSON_FILE)
