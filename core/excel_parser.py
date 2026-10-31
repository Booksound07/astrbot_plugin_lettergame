import json
import zipfile
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Tuple

# 零宽类字符，肉眼完全看不到，但会让匹配对不上
ZERO_WIDTH = {"\u200b", "\ufeff"}


def normalize_ws(text: str) -> str:
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


def split_aliases(alias_str: str) -> List[str]:
    """别名以全角逗号为主，半角逗号也认，混写不会漏"""
    parts = re.split(r"[，,]", alias_str)
    return [a.strip() for a in parts if a.strip()]

NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

def read_shared_strings(z):
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
    value = 0
    for ch in col:
        value = value * 26 + (ord(ch.upper()) - 64)
    return value

def read_sheet(z, shared_strings):
    data = z.read("xl/worksheets/sheet1.xml")
    root = ET.fromstring(data)
    rows = []
    for row in root.findall(".//a:row", NS):
        row_data = {}
        for cell in row.findall("a:c", NS):
            ref = cell.attrib.get("r", "")
            col = "".join(x for x in ref if x.isalpha())
            col_num = col_to_num(col)
            value = ""
            cell_type = cell.attrib.get("t")
            v = cell.find("a:v", NS)
            if v is None:
                # 内联字符串：<is><t>...</t></is>（openpyxl 等工具会这么写）
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
                    value = shared_strings[idx]
            else:
                value = v.text
            row_data[col_num] = value
        rows.append(row_data)
    return rows

def find_column(header_row, target_name):
    for col, value in header_row.items():
        if normalize_ws(str(value)).strip() == target_name:
            return col
    return None

def parse_excel(file_path: Path, title_column: str, standard_column: str) -> Tuple[List[Dict], List[str], List[str], Dict[str, List[str]]]:
    """
    解析 Excel 文件，返回 (songs, duplicates, headers)
    songs: [{"title": ..., "is_standard": bool}, ...]
    duplicates: 重复的标准曲名列表
    headers: 实际表头列表（用于错误提示）
    """
    with zipfile.ZipFile(file_path, "r") as z:
        shared_strings = read_shared_strings(z)
        rows = read_sheet(z, shared_strings)

    if len(rows) < 2:
        raise ValueError("Excel内容不足，至少需要表头行和一行数据")

    header_row = rows[0]
    # 提取实际表头
    headers = []
    for col_num in sorted(header_row.keys()):
        headers.append(normalize_ws(str(header_row[col_num])).strip())

    title_col = find_column(header_row, title_column)
    standard_col = find_column(header_row, standard_column)

    if title_col is None:
        raise ValueError(f"未找到列：{title_column}")
    if standard_col is None:
        raise ValueError(f"未找到列：{standard_column}")
    
    # ===== 检测别名列 =====
    alias_col = None
    alias_col_names = ["别名", "alias", "aliases", "别称", "缩写"]
    for alias_name in alias_col_names:
        col = find_column(header_row, alias_name)
        if col is not None:
            alias_col = col
            break

    songs = []
    alias_map = {}
    standard_titles = set()
    duplicates = []

    for row in rows[1:]:
        title = normalize_ws(str(row.get(title_col, ""))).strip()
        if not title:
            continue

        raw_standard = row.get(standard_col, "")

        if isinstance(raw_standard, bool):
            is_standard = raw_standard

        elif isinstance(raw_standard, (int, float)):
            is_standard = raw_standard == 1

        else:
            raw_standard = str(raw_standard).strip().lower()

            is_standard = raw_standard in {
                "1",
                "1.0",
                "true",
                "是"
            }

        songs.append({"title": title, "is_standard": is_standard})

        if is_standard:
            key = title.lower()
            if key in standard_titles:
                duplicates.append(title)
            standard_titles.add(key)
            
            # ===== 提取别名 =====
            if alias_col is not None:
                alias_str = normalize_ws(str(row.get(alias_col, ""))).strip()
                if alias_str:
                    aliases = split_aliases(alias_str)
                    if aliases:
                        if title in alias_map:
                            alias_map[title].extend(aliases)
                        else:
                            alias_map[title] = aliases

    # 别名去重
    for title in alias_map:
        alias_map[title] = list(dict.fromkeys(alias_map[title]))
    return songs, duplicates, headers, alias_map