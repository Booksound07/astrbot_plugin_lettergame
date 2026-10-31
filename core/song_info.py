from .alias_manager import get_aliases
from .custom_bank_manager import get_all_custom_aliases_for_song

async def show_song_info(event, song, user_id: str = None):
    info = []
    info.append(f"曲名：{song.get('title','')}")
    info.append(f"格式码：{song.get('format_code','')}")

    # 元数据信息
    if song.get("duration"):
        info.append(f"时长：{song['duration']}")
    if song.get("bpm"):
        info.append(f"BPM：{song['bpm']}")
    if song.get("artist"):
        info.append(f"曲师：{song['artist']}")
    if song.get("charter"):
        info.append(f"谱师：{song['charter']}")
    if song.get("illustrator"):
        info.append(f"画师：{song['illustrator']}")
    if song.get("chapter"):
        info.append(f"章节：{song['chapter']}")
    if song.get("package"):
        info.append(f"曲包：{song['package']}")

    bank = song.get("bank", "")

    # 判断是否为自定义题库
    if bank.startswith("custom_"):
        # 自定义题库：只显示自定义别名
        custom_aliases = []
        if user_id:
            custom_aliases = get_all_custom_aliases_for_song(user_id, song["title"])
            custom_aliases = list(dict.fromkeys(custom_aliases))
        if custom_aliases:
            info.append("自定义题库已有别名：")
            for i, alias in enumerate(custom_aliases, 1):
                info.append(f"  {i}. {alias}")
        else:
            info.append("自定义题库已有别名：无")
    else:
        # 默认题库：显示默认别名
        default_aliases = get_aliases(bank, song["title"])
        default_aliases = list(dict.fromkeys(default_aliases))
        if default_aliases:
            info.append("已有别名：")
            for i, alias in enumerate(default_aliases, 1):
                info.append(f"  {i}. {alias}")
        else:
            info.append("已有别名：无")

        # 如果用户有自定义别名，也显示（针对默认题库中的同名曲）
        if user_id:
            custom_aliases = get_all_custom_aliases_for_song(user_id, song["title"])
            custom_aliases = list(dict.fromkeys(custom_aliases))
            if custom_aliases:
                info.append("自定义题库已有别名：")
                for i, alias in enumerate(custom_aliases, 1):
                    info.append(f"  {i}. {alias}")

    await event.send(event.plain_result("\n".join(info)))