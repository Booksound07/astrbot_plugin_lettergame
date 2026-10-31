import re

def search_format_code(all_songs, query):
    nums = [int(x) for x in query.split("-")]

    matches = []

    for song in all_songs:

        title = song.get("title", "")

        words = title.split()

        if len(words) != len(nums):
            continue

        ok = True

        for w, n in zip(words, nums):

            if len(w) != n:
                ok = False
                break

        if ok:
            matches.append(song)

    return matches

def search_mask(all_songs, query, excluded_letters=None, mode=0):
    """
    逐字比对掩码查询，支持空格精确匹配。
    如果指定 excluded_letters，则 * 位置不能匹配这些字母。
    mode: 0=默认, 1=无视空格, 2=空格=* , 3=无视已开字母（*匹配所有字符）
    """
    if excluded_letters is None:
        excluded_letters = set()

    # 统一转小写：保证排除字母的比对无视大小写
    excluded_lower = {str(x).lower() for x in excluded_letters}

    matches = []

    for song in all_songs:
        title = song.get("title", "")

        if mode == 1:
            # 无视空格模式：删除所有空格后比较
            title_masked = title.replace(" ", "")
            query_masked = query.replace(" ", "")
            if len(title_masked) != len(query_masked):
                continue
            ok = True
            for qc, tc in zip(query_masked, title_masked):
                if qc == "*":
                    if tc.lower() in excluded_lower:
                        ok = False
                        break
                else:
                    if qc.lower() != tc.lower():
                        ok = False
                        break
            if ok:
                matches.append(song)
            continue

        elif mode == 2:
            # 空格=*模式：空格和*都匹配任意字符（包括空格和非空格）
            if len(title) != len(query):
                continue
            ok = True
            for qc, tc in zip(query, title):
                if qc == "*" or qc == " ":
                    continue
                else:
                    if qc.lower() != tc.lower():
                        ok = False
                        break
            if ok:
                matches.append(song)
            continue

        elif mode == 3:
            # 无视已开字母模式：*匹配所有字符，不检查excluded_letters
            # 等同于默认模式但去掉excluded_letters检查
            if len(query) != len(title):
                continue
            ok = True
            for qc, tc in zip(query, title):
                if qc == " ":
                    if tc != " ":
                        ok = False
                        break
                elif qc == "*":
                    # 不检查 excluded_letters，直接通过
                    continue
                else:
                    if qc.lower() != tc.lower():
                        ok = False
                        break
            if ok:
                matches.append(song)
            continue

        # 默认模式（mode=0）：原有逻辑，检查excluded_letters
        if len(query) != len(title):
            continue

        ok = True
        for qc, tc in zip(query, title):
            if qc == " ":
                if tc != " ":
                    ok = False
                    break
            elif qc == "*":
                if tc.isspace() or tc.lower() in excluded_lower:
                    ok = False
                    break
            else:
                if qc.lower() != tc.lower():
                    ok = False
                    break

        if ok:
            matches.append(song)

    return matches