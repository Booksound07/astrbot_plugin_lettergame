from .preset_manager import get_preset, save_preset, delete_preset, preview_preset
from .preset_upload_manager import cancel_upload
from . import helpers

_pending_edit = {}


def start_edit(
    user_id,
    preset_ids
):

    _pending_edit[user_id] = {
        "state": "select",
        "mode": None,
        "preset_ids": preset_ids,
        "preset_id": None
    }


def set_preset(
    user_id,
    preset_id
):

    if user_id not in _pending_edit:
        return

    _pending_edit[user_id]["preset_id"] = preset_id

    _pending_edit[user_id]["state"] = "menu"


def set_state(
    user_id,
    state
):

    if user_id not in _pending_edit:
        return

    _pending_edit[user_id]["state"] = state

def set_mode(
    user_id,
    mode
):

    if user_id not in _pending_edit:
        return

    _pending_edit[user_id]["mode"] = mode

def get_edit_info(
    user_id
):

    return _pending_edit.get(
        user_id
    )


def is_editing(
    user_id
):

    return (
        user_id
        in
        _pending_edit
    )


def cancel_edit(
    user_id
):

    _pending_edit.pop(
        user_id,
        None
    )
    
async def process_edit_input(user_id: str, text: str, event) -> tuple[bool, str | None]:
    """
    处理预设编辑的输入
    返回 (handled, reply_text)
    handled=True 表示消息已被处理，不再继续
    reply_text 为要发送的回复，可为 None
    """
    info = get_edit_info(user_id)
    if not info:
        return False, None

    state = info["state"]

    # ===== 选择题目 =====
    if state == "select":
        if not text.isdigit():
            return True, None
        index = int(text)
        preset_ids = info["preset_ids"]
        if index < 1 or index > len(preset_ids):
            return True, "序号超出范围。"
        preset_id = preset_ids[index - 1]
        set_preset(user_id, preset_id)
        return True, f"编号：{preset_id}\n\n1. 编辑可开群\n2. 编辑可开启人员\n3. 删除题目\n4. 查看题目详情\n\n发送“返回”退出。"

    # ===== 主菜单 =====
    if state == "menu":
        if text == "返回":
            cancel_edit(user_id)
            return True, "已退出。"

        preset_id = info["preset_id"]

        if text == "1":
            set_state(user_id, "group")
            return True, "请输入允许开启的群号。\n\n一行一个。\n\n发送“设置全部”或留空表示所有群均可开启。\n发送“返回”退出。"

        if text == "2":
            set_state(user_id, "user")
            return True, "请输入允许开启的 QQ 号。\n\n一行一个。\n\n作者默认拥有权限。\n留空表示仅作者可开启。\n发送“设置全部”表示所有人均可开启。\n发送“返回”退出。"

        if text == "3":
            set_state(user_id, "delete_confirm")
            return True, f"确定删除题目 #{preset_id} 吗？\n\n1. 是\n2. 否\n\n发送“返回”退出。"

        if text == "4":
            item = get_preset(preset_id)
            preview_lines, count = preview_preset(item)
            reply = f"编号：{preset_id}\n\n题目预览：\n\n" + "\n".join(preview_lines) + f"\n\n共 {count} 题。\n\n输入“返回”回到上一页。"
            set_state(user_id, "info")
            return True, reply

        return True, "请输入 1~4。"

    # ===== 编辑群 =====
    if state == "group":
        if text == "返回":
            set_state(user_id, "menu")
            preset_id = info["preset_id"]
            return True, f"编号：{preset_id}\n\n1. 编辑可开群\n2. 编辑可开启人员\n3. 删除题目\n4. 查看题目详情"

        preset_id = info["preset_id"]
        item = get_preset(preset_id)
        text = text.strip()

        if text == "" or text == "设置全部":
            item["allowed_groups"] = []
        else:
            groups = []
            for x in text.splitlines():
                x = x.strip()
                if not x:
                    continue
                if not x.isdigit():
                    return True, "群号格式错误。\n\n请重新输入。\n一行一个群号。\n发送“设置全部”表示所有群可开启。"
                groups.append(x)
            item["allowed_groups"] = groups

        save_preset(item)
        set_state(user_id, "menu")
        return True, "可开群设置成功。\n发送“返回”以结束设置或发送对应序号继续编辑。"

    # ===== 编辑用户 =====
    if state == "user":
        if text == "返回":
            set_state(user_id, "menu")
            preset_id = info["preset_id"]
            return True, f"编号：{preset_id}\n\n1. 编辑可开群\n2. 编辑可开启人员\n3. 删除题目\n4. 查看题目详情"

        preset_id = info["preset_id"]
        item = get_preset(preset_id)
        text = text.strip()

        if text == "设置全部":
            item["allowed_users"] = None
        elif text == "":
            item["allowed_users"] = []
        else:
            users = []
            for x in text.splitlines():
                x = x.strip()
                if not x:
                    continue
                if not x.isdigit():
                    return True, "QQ号格式错误。\n\n请重新输入。\n一行一个 QQ 号。\n留空表示仅作者可开启。\n发送“设置全部”表示所有人可开启。"
                users.append(x)
            item["allowed_users"] = users

        save_preset(item)
        set_state(user_id, "menu")
        return True, "可开启人员设置成功。\n发送“返回”以结束设置或发送对应序号继续编辑。"

    # ===== 删除确认 =====
    if state == "delete_confirm":
        preset_id = info["preset_id"]
        item = get_preset(preset_id)

        if text in ["2", "返回"]:
            set_state(user_id, "menu")
            return True, f"编号：{preset_id}\n\n1. 编辑可开群\n2. 编辑可开启人员\n3. 删除题目\n4. 查看题目详情"

        if text != "1":
            return True, "请输入 1、2 或“返回”。"

        # 权限检查
        if event.get_sender_id() != item["uploader"] and not helpers.is_admin(event):
            cancel_edit(user_id)
            return True, "权限不足，无法删除该题目。"

        ok = delete_preset(preset_id)
        cancel_edit(user_id)
        if ok:
            return True, "删除成功，已自动退出编辑模式。"
        else:
            return True, "删除失败。"

    # ===== 查看详情 =====
    if state == "info":
        if text != "返回":
            return True, "输入“返回”回到上一页。"
        preset_id = info["preset_id"]
        set_state(user_id, "menu")
        return True, f"编号：{preset_id}\n\n1. 编辑可开群\n2. 编辑可开启人员\n3. 删除题目\n4. 查看题目详情"

    return False, None