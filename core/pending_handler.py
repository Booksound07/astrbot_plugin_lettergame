import time
from astrbot.api import logger
from .pending_manager import get_pending_query, remove_pending_query, set_pending_query
from .alias_manager import get_aliases, add_alias_to_file, remove_alias_from_file
from .alias_approval import AliasApprovalManager
from .custom_bank_manager import add_custom_alias, remove_custom_alias
from .song_bank import SongBankManager
from .helpers import is_admin, require_group_at
from .constants import COMMAND_SET
from .song_info import show_song_info

# 全局引用（由 main.py 传入）
gm = None
bank_manager = None
approval_mgr = None
pending_upload = {}

def init_handlers(gm_instance, bank_manager_instance, approval_mgr_instance):
    global gm, bank_manager, approval_mgr
    gm = gm_instance
    bank_manager = bank_manager_instance
    approval_mgr = approval_mgr_instance

async def handle_pending_query(event, text, key):
    # 群聊必须 @（或唤醒），否则不把这条消息当序号输入
    if require_group_at(event):
        return False

    # 空文本直接放行：插件注入的合成事件、平台心跳等没有真实内容，
    # 不能把它当成“用户输错序号”去提示。
    if not (text or "").strip():
        return False

    data = get_pending_query(key)
    if not data:
        return False
    if time.time() > data["expire"]:
        remove_pending_query(key)
        await event.send(event.plain_result("选择已超时"))
        return True
    
    is_command = False
    for cmd in COMMAND_SET:
        if text == cmd or text.startswith(cmd + " "):
            is_command = True
            break
        
    if is_command:
        remove_pending_query(key)
        return False

    if not text.isdigit():
        await event.send(event.plain_result("请输入正确序号"))
        return True

    idx = int(text) - 1
    if not (0 <= idx < len(data["songs"])):
        total = len(data["songs"])
        await event.send(
            event.plain_result(f"请输入正确序号（1-{total}）")
        )
        return True

    song = data["songs"][idx]
    remove_pending_query(key)
    from .pending_manager import set_pending_alias
    from .constants import PENDING_ALIAS_TIMEOUT
    set_pending_alias(key, {"song": song, "expire": time.time() + PENDING_ALIAS_TIMEOUT})
    await show_song_info(event, song, event.get_sender_id())
    return True


async def handle_alias_choice(event, text, key, alias_type: str):
    """
    处理别名选择（加别名或删别名）
    alias_type: "add" 或 "delete"
    """
    pending = get_pending_query(key)
    if not pending or pending.get("action") != f"{alias_type}_alias_choice":
        return False
    
    if text not in ["1", "2", "3"]:
        return False
    
    choice = text
    title = pending["title"]
    alias = pending["alias"]
    custom_bank_id = pending.get("custom_bank_id")
    default_bank = pending.get("default_bank")
    user_id = event.get_sender_id()
    
    if alias_type == "add":
        # ---------- 加别名处理 ----------
        if choice == "1":
            # 仅自定义
            if add_custom_alias(user_id, custom_bank_id, title, alias):
                await event.send(event.plain_result(f"已添加别名：{title} -> {alias}"))
            else:
                await event.send(event.plain_result("该别名已存在。"))
        elif choice == "2":
            # 仅默认
            default_song = _find_default_song(title)
            if default_song:
                if is_admin(event):
                    aliases = get_aliases(default_song["bank"], default_song["title"])
                    if alias.lower() in [x.lower() for x in aliases]:
                        await event.send(event.plain_result("该别名已存在。"))
                    else:
                        add_alias_to_file(default_song["bank"], default_song["title"], alias)
                        await event.send(event.plain_result(f"管理员添加别名：{default_song['title']} -> {alias}"))
                else:
                    await _submit_alias_for_approval(event, default_song, alias)
            else:
                await event.send(event.plain_result("内置题库中未找到该曲目。"))
        elif choice == "3":
            # 都加
            add_custom_alias(user_id, custom_bank_id, title, alias)
            default_song = _find_default_song(title)
            if default_song:
                if is_admin(event):
                    aliases = get_aliases(default_song["bank"], default_song["title"])
                    if alias.lower() not in [x.lower() for x in aliases]:
                        add_alias_to_file(default_song["bank"], default_song["title"], alias)
                        await event.send(event.plain_result(f"已添加别名至自定义题库，管理员添加内置题库别名：{default_song['title']} -> {alias}"))
                    else:
                        await event.send(event.plain_result(f"已添加别名至自定义题库，内置题库中已存在该别名。"))
                else:
                    await _submit_alias_for_approval(event, default_song, alias, custom_added=True)
            else:
                await event.send(event.plain_result("已添加别名至自定义题库，内置题库中未找到该曲目。"))
        remove_pending_query(key)
        return True

    else:  # alias_type == "delete"
        # ---------- 删别名处理 ----------
        if choice == "1":
            # 仅删除自定义
            if remove_custom_alias(user_id, custom_bank_id, title, alias):
                await event.send(event.plain_result(f"已删除别名：{title} -> {alias}"))
            else:
                await event.send(event.plain_result("删除失败，该别名可能不存在。"))
        elif choice == "2":
            # 普通用户：取消；管理员：仅删默认
            if not is_admin(event):
                await event.send(event.plain_result("你只能删除自定义题库中的别名！本次操作已取消。"))
            else:
                if default_bank:
                    remove_alias_from_file(default_bank, title, alias)
                    await event.send(event.plain_result(f"已删除别名：{title} -> {alias}（仅内置）"))
                else:
                    await event.send(event.plain_result("内置题库中未找到该曲目。"))
        elif choice == "3":
            # 仅管理员有选项3：都删
            if not is_admin(event):
                await event.send(event.plain_result("无效的选项。"))
                remove_pending_query(key)
                return True
            # 删除自定义
            remove_custom_alias(user_id, custom_bank_id, title, alias)
            # 删除默认
            if default_bank:
                remove_alias_from_file(default_bank, title, alias)
                await event.send(event.plain_result(f"已删除别名：{title} -> {alias}（自定义和内置）"))
            else:
                await event.send(event.plain_result(f"已删除自定义题库中的别名，未找到内置题库中的别名。"))
        else:
            await event.send(event.plain_result("请输入正确的选项。"))
            remove_pending_query(key)
            return True

        remove_pending_query(key)
        return True

def _find_default_song(title):
    """在内置题库中查找歌曲"""
    for song in bank_manager.get_all_songs():
        if song["title"] == title:
            return song
    return None

async def _submit_alias_for_approval(event, default_song, alias, custom_added=False):
    """提交别名审核"""
    for item in approval_mgr.list_all():
        if item["title"] == default_song["title"] and item["alias"].lower() == alias.lower():
            await event.send(event.plain_result(f"该别名已经提交审核（编号 {item['id']}）"))
            return
    aid = approval_mgr.add(default_song["bank"], default_song["title"], alias, event.get_sender_id())
    if custom_added:
        await event.send(event.plain_result(f"已添加别名至自定义题库，已提交内置题库别名审核 | 编号 {aid} | 歌名 {default_song['title']} | 别名 {alias}"))
    else:
        await event.send(event.plain_result(f"已提交审核 | 编号 {aid} | 歌名 {default_song['title']} | 别名 {alias}"))