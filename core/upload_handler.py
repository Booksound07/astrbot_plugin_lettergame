import asyncio
import time
import requests
import json
from pathlib import Path
from astrbot.api import logger

from .custom_bank_manager import (
    get_banks_list, get_bank, delete_bank, rename_bank,
    create_bank, overwrite_bank, get_custom_songs,
    get_custom_aliases, add_custom_alias, remove_custom_alias,
    get_all_custom_aliases, get_custom_bank_id_by_song,
    import_custom_aliases, export_custom_aliases,
    parse_alias_text
)
from .excel_parser import parse_excel
from .text_parser import parse_text
from .user_settings import (
    disable_custom_bank, enable_custom_bank,
    get_disabled_custom_banks, is_custom_bank_disabled
)

PLUGIN_TEMP_DIR = Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_lettergame" / "tmp"

# 全局状态（由 main.py 传入）
pending_upload = {}

def _download_to_file(url: str, dest: Path, timeout: int = 30) -> Path:
    """同步下载并写入磁盘；该函数会阻塞，调用方必须用 asyncio.to_thread 包一层。"""
    resp = requests.get(url, timeout=timeout)
    with open(dest, "wb") as f:
        f.write(resp.content)
    return dest


def get_upload_state(umo: str):
    return pending_upload.get(umo)

def set_upload_state(umo: str, state: dict):
    pending_upload[umo] = state

def clear_upload_state(umo: str):
    pending_upload.pop(umo, None)

def is_upload_state_active(umo: str) -> bool:
    return umo in pending_upload


async def handle_upload_file(event, user_id, umo, text, upload_state):
    """处理 awaiting_file 状态"""
    has_file = False
    file_path = None
    headers = []

    for comp in event.message_obj.message:
        if comp.type == "File":
            has_file = True

            temp_path = (
                PLUGIN_TEMP_DIR
                / f"{user_id}_{int(time.time())}.xlsx"
            )

            # 下载和落盘放进线程，避免同步 requests 阻塞事件循环
            await asyncio.to_thread(_download_to_file, comp.url, temp_path)

            file_path = temp_path
            break

    # 没有文件时，才按照纯文本处理
    if not has_file:

        if not text or not text.strip():
            return True

        if text == "取消":
            clear_upload_state(umo)

            await event.send(
                event.plain_result("已取消操作。")
            )

            return True

    if has_file and file_path and str(file_path).lower().endswith(".xlsx"):
        try:
            songs, duplicates, headers, alias_map = parse_excel(
                file_path,
                upload_state["title_column"],
                upload_state["standard_column"]
            )
            file_path.unlink(missing_ok=True)
            upload_state["step"] = "awaiting_name"
            upload_state["songs"] = songs
            upload_state["duplicates"] = duplicates
            upload_state["alias_map"] = alias_map
            upload_state["is_excel"] = True
            await event.send(event.plain_result(
                f"✅ 上传成功！共 {len(songs)} 个题目。\n\n"
                f"请输入这个题库的名称（允许中英文、数字、空格），"
                f"或者发送“取消”取消本次上传。"
            ))
        except ValueError as e:
            error_msg = str(e)
            if "未找到列" in error_msg:
                await event.send(event.plain_result(
                    f"❌ 上传失败：未找到必要的列。\n\n"
                    f"请确保 Excel 文件包含以下两列（列名必须完全一致）：\n"
                    f"  · 曲名\n"
                    f"  · 是否是标准曲名\n\n"
                    f"请重新发送正确的 Excel 文件，或发送“取消”取消本次上传。"
                ))
            else:
                await event.send(event.plain_result(
                    f"❌ 上传失败：{error_msg}\n\n"
                    f"请重新发送正确的 Excel 文件，或发送“取消”取消本次上传。"
                ))
            # 保持状态，让用户重试
            file_path.unlink(missing_ok=True)
        except Exception as e:
            await event.send(event.plain_result(
                f"❌ 上传失败：{e}\n\n"
                f"请重新发送正确的 Excel 文件，或发送“取消”取消本次上传。"
            ))
            file_path.unlink(missing_ok=True)
            # 保持状态，让用户重试
        return True
    elif has_file and file_path:
        # 不是 .xlsx 文件
        await event.send(event.plain_result(
            "格式错误！请重新发送 .xlsx 格式的 Excel 文件，或发送“取消”取消本次上传。"
        ))
        file_path.unlink(missing_ok=True)
        # 保持状态，让用户重试
        return True
    else:
        # 纯文本
        songs = parse_text(text)
        if not songs:
            await event.send(event.plain_result(
                "未检测到有效内容。请重新发送每行一个题目的文本内容，或发送 Excel 文件，或发送“取消”取消本次上传。"
            ))
            # 保持状态，让用户重试
            return True
        upload_state["step"] = "awaiting_name"
        upload_state["songs"] = songs
        upload_state["duplicates"] = []
        upload_state["is_excel"] = False
        await event.send(event.plain_result(
            f"✅ 解析成功！共 {len(songs)} 个题目。\n\n"
            f"请输入这个题库的名称（允许中英文、数字、空格），"
            f"或者发送“取消”取消本次上传。"
        ))
        return True

async def handle_upload_name(event, user_id, umo, text, upload_state):
    """处理 awaiting_name 状态"""
    name = text.strip()
    if not name:
        await event.send(event.plain_result(
            "名称不能为空，请重新输入名称，或发送“取消”取消本次上传。"
        ))
        return True

    existing = [b for b in get_banks_list(user_id) if b["name"] == name]
    if existing:
        upload_state["step"] = "awaiting_confirm"
        upload_state["pending_name"] = name
        upload_state["existing_bank_id"] = existing[0]["id"]
        await event.send(event.plain_result(
            f"⚠️ 你已有一个名为“{name}”的自定义题库（ID：{existing[0]['id']}）\n\n"
            f"输入 1：覆盖旧题库（旧数据将被删除，别名保留）\n"
            f"输入 2：取消本次上传，保留旧题库\n\n"
            f"请输入 1 或 2："
        ))
        return True

    meta_info = {
        "title_column": upload_state["title_column"],
        "standard_column": upload_state["standard_column"],
        "is_excel": upload_state["is_excel"],
        "duplicates": upload_state.get("duplicates", [])
    }
    bank_id = create_bank(user_id, name, upload_state["songs"], meta_info)

    # ===== 检测是否有别名数据 =====
    alias_map = upload_state.get("alias_map", {})
    alias_count = sum(len(aliases) for aliases in alias_map.values())

    if alias_count > 0:
        # 有别名 → 进入别名自动确认状态
        upload_state["step"] = "awaiting_alias_auto_confirm"
        upload_state["bank_id"] = bank_id
        upload_state["bank_name"] = name
        upload_state["song_count"] = len(upload_state["songs"])
        
        await event.send(event.plain_result(
            f"✅ 自定义题库创建成功！\n\n"
            f"题库 ID：{bank_id}\n"
            f"名称：{name}\n"
            f"歌曲数量：{len(upload_state['songs'])} 首\n\n"
            f"检测到 Excel 中包含别名数据（共 {alias_count} 个别名），是否立即导入？\n"
            f"输入 1：立即导入\n"
            f"输入 2：稍后使用 /导入别名 手动导入\n\n"
            f"请输入 1 或 2："
        ))
        return True

    # 没有别名 → 走原逻辑
    upload_state["step"] = "awaiting_alias_choice"
    upload_state["bank_id"] = bank_id
    upload_state["bank_name"] = name
    upload_state["song_count"] = len(upload_state["songs"])

    await event.send(event.plain_result(
        f"✅ 自定义题库创建成功！\n\n"
        f"题库 ID：{bank_id}\n"
        f"名称：{name}\n"
        f"歌曲数量：{len(upload_state['songs'])} 首\n\n"
        f"是否立即为该题库导入别名？\n"
        f"输入 1：是，现在导入别名\n"
        f"输入 2：否，稍后使用 /导入别名 手动导入\n\n"
        f"请输入 1 或 2："
    ))
    return True


async def handle_upload_confirm(event, user_id, umo, text, upload_state):
    """处理 awaiting_confirm 状态"""
    choice = text.strip()
    if choice == "1":
        old_bank_id = upload_state["existing_bank_id"]
        meta_info = {
            "title_column": upload_state["title_column"],
            "standard_column": upload_state["standard_column"],
            "is_excel": upload_state["is_excel"],
            "duplicates": upload_state.get("duplicates", [])
        }
        if overwrite_bank(user_id, old_bank_id, upload_state["pending_name"], upload_state["songs"], meta_info):
            clear_upload_state(umo)
            await event.send(event.plain_result(
                f"✅ 旧题库已覆盖！\n\n"
                f"题库 ID：{old_bank_id}\n"
                f"名称：{upload_state['pending_name']}\n"
                f"歌曲数量：{len(upload_state['songs'])} 首\n"
                f"（别名已保留）"
            ))
        else:
            await event.send(event.plain_result(
                "❌ 覆盖失败，请发送“取消”取消本次操作，然后重新使用 /上传题库 后再次尝试。"
            ))
            # 保持状态，让用户选择取消或重试
    elif choice == "2":
        clear_upload_state(umo)
        await event.send(event.plain_result("已取消上传，保留旧题库。"))
    else:
        await event.send(event.plain_result("请输入 1 或 2。"))
        return True
    return True


async def handle_upload_alias_choice(event, user_id, umo, text, upload_state):
    """处理 awaiting_alias_choice 状态"""
    choice = text.strip()
    if choice == "1":
        upload_state["step"] = "awaiting_alias_method"
        await event.send(event.plain_result(
            "请选择别名导入方式：\n"
            "1. 发送 Excel 文件（.xlsx）\n"
            "2. 发送纯文本（每行一个曲目，全角逗号分隔别名）\n\n"
            "请输入 1 或 2："
        ))
    elif choice == "2":
        bank_id = upload_state["bank_id"]
        clear_upload_state(umo)
        await event.send(event.plain_result(f"上传流程已结束，稍后可使用 /导入别名 {bank_id} 导入别名。"))
    else:
        await event.send(event.plain_result("请输入 1 或 2。"))
        return True
    return True


async def handle_alias_method(event, user_id, umo, text, upload_state):
    """处理 awaiting_alias_method 状态"""
    choice = text.strip()
    if choice == "1":
        upload_state["step"] = "awaiting_import_file"
        await event.send(event.plain_result(
            "请发送包含别名的 Excel 文件（.xlsx）。\n"
            "格式要求：至少包含“曲名”和“别名”两列（自动识别），每个曲名对应的别名必须写在同一行，每个别名之间用全角逗号隔开。"
        ))
    elif choice == "2":
        upload_state["step"] = "awaiting_import_text"
        await event.send(event.plain_result(
            "📝 请发送该题库的别名文本。\n\n"
            "格式要求：\n"
            "- 每行对应一首曲目（顺序必须和题库顺序一致）\n"
            "- 别名之间用全角逗号（，）分隔\n"
            "- 例如：\n"
            "  无限天堂，IH\n"
            "  rip，安息\n\n"
            "发送“取消”取消导入。"
        ))
    else:
        await event.send(event.plain_result("请输入 1 或 2。"))
        return True
    return True


async def handle_import_file(event, user_id, umo, text, upload_state):
    """处理 awaiting_import_file 状态"""

    if text == "取消":
        clear_upload_state(umo)

        await event.send(
            event.plain_result("已取消导入。")
        )

        return True

    has_file = False
    file_path = None

    for comp in event.message_obj.message:
        if comp.type == "File":
            has_file = True

            temp_path = (
                PLUGIN_TEMP_DIR
                / f"{user_id}_import_{int(time.time())}.xlsx"
            )

            # 下载和落盘放进线程，避免同步 requests 阻塞事件循环
            await asyncio.to_thread(_download_to_file, comp.url, temp_path)

            file_path = temp_path
            break

    if has_file and file_path and str(file_path).lower().endswith(".xlsx"):

        try:
            # ==================================================
            # 使用统一的 Excel 解析器
            # 自动识别：
            #   曲名
            #   是否是标准曲名
            #   别名 / alias / aliases / 别称 / 缩写
            # ==================================================

            songs, duplicates, headers, alias_data = parse_excel(
                file_path,
                "曲名",
                "是否是标准曲名"
            )

            file_path.unlink(missing_ok=True)

            # 没有找到任何别名
            if not alias_data:
                await event.send(
                    event.plain_result(
                        "未检测到有效别名数据。\n\n"
                        "请确保 Excel 包含以下表头：\n"
                        "  · 曲名\n"
                        "  · 是否是标准曲名\n"
                        "  · 别名\n\n"
                        "其中“别名”也可以使用：\n"
                        "  · alias\n"
                        "  · aliases\n"
                        "  · 别称\n"
                        "  · 缩写\n\n"
                        "别名之间请使用全角逗号“，”分隔。\n\n"
                        "请重新发送正确的 Excel 文件，"
                        "或发送“取消”取消导入。"
                    )
                )

                # 保持状态，让用户重试
                return True

            # ==================================================
            # 执行别名导入
            # ==================================================

            bank_id = upload_state["bank_id"]

            success, failed = import_custom_aliases(
                user_id,
                bank_id,
                alias_data
            )

            clear_upload_state(umo)

            await event.send(
                event.plain_result(
                    f"✅ 别名导入完成！\n"
                    f"成功：{success} 个别名\n"
                    f"失败（重复或无效）：{failed} 个"
                )
            )

        except ValueError as e:

            await event.send(
                event.plain_result(
                    f"❌ Excel 格式错误：{e}\n\n"
                    f"当前导入格式要求：\n"
                    f"  · 曲名\n"
                    f"  · 是否是标准曲名\n"
                    f"  · 别名\n\n"
                    f"其中“别名”也可以使用 alias、aliases、"
                    f"别称或缩写作为表头。\n\n"
                    f"请重新发送正确的 Excel 文件，"
                    f"或发送“取消”取消导入。"
                )
            )

            if file_path:
                file_path.unlink(missing_ok=True)

            # 保持状态，让用户重试

        except Exception as e:

            await event.send(
                event.plain_result(
                    f"❌ 导入失败：{e}\n\n"
                    f"请重新发送正确的 Excel 文件，"
                    f"或发送“取消”取消导入。"
                )
            )

            if file_path:
                file_path.unlink(missing_ok=True)

            # 保持状态，让用户重试

    elif has_file and file_path:

        await event.send(
            event.plain_result(
                "格式错误！请重新发送 .xlsx 格式的 Excel 文件，"
                "或发送“取消”取消导入。"
            )
        )

        file_path.unlink(missing_ok=True)

        # 保持状态，让用户重试

    else:

        await event.send(
            event.plain_result(
                "请发送 .xlsx 格式的 Excel 文件，"
                "或发送“取消”取消导入。"
            )
        )

        # 保持状态，让用户重试

    return True

async def handle_import_text(event, user_id, umo, text, upload_state):
    """处理 awaiting_import_text 状态"""
    if text == "取消":
        clear_upload_state(umo)
        await event.send(event.plain_result("已取消导入。"))
        return True

    bank_id = upload_state["bank_id"]
    bank_data = get_bank(user_id, bank_id)
    if not bank_data:
        # 题库可能被删了，清空状态
        clear_upload_state(umo)
        await event.send(event.plain_result("❌ 题库不存在，请重新使用 /导入别名 后再次尝试。"))
        return True

    songs = bank_data["songs"]
    alias_data = parse_alias_text(text, songs)
    if not alias_data:
        await event.send(event.plain_result(
            "未检测到有效别名数据。请检查格式后重新发送，或发送“取消”取消导入。\n\n"
            "格式要求：\n"
            "- 每行对应一首曲目（顺序必须和题库顺序一致）\n"
            "- 别名之间用全角逗号（，）分隔\n"
            "- 例如：\n"
            "  无限天堂，IH\n"
            "  rip，安息"
        ))
        # 保持状态，让用户重试
        return True

    success, failed = import_custom_aliases(user_id, bank_id, alias_data)
    clear_upload_state(umo)
    await event.send(event.plain_result(
        f"✅ 别名导入完成！\n"
        f"成功：{success} 个别名\n"
        f"失败（重复或无效）：{failed} 个"
    ))
    return True


async def handle_del_confirm(event, user_id, umo, text, upload_state):
    """处理 awaiting_del_confirm 状态"""
    choice = text.strip()
    if choice == "1":
        bank_id = upload_state["bank_id"]
        if delete_bank(user_id, bank_id):
            await event.send(event.plain_result(f"✅ 题库 {bank_id} 已删除。"))
        else:
            await event.send(event.plain_result("删除失败。"))
        clear_upload_state(umo)
    elif choice == "2":
        clear_upload_state(umo)
        await event.send(event.plain_result("已取消删除。"))
    else:
        await event.send(event.plain_result("请输入 1 或 2。"))
        return True
    return True


async def handle_import_confirm(event, user_id, umo, text, upload_state):
    """处理 awaiting_import_confirm 状态"""
    choice = text.strip()
    if choice == "1":
        method = upload_state.get("method")
        bank_id = upload_state["bank_id"]
        target_type = upload_state["target_type"]
        if method == "excel":
            set_upload_state(umo, {
                "step": "awaiting_import_file",
                "bank_id": bank_id,
                "target_type": target_type
            })
            await event.send(event.plain_result("请发送包含别名的 Excel 文件（.xlsx）。\n第一列：曲名，第二列：别名（全角逗号分隔）。"))
        elif method == "文本":
            set_upload_state(umo, {
                "step": "awaiting_import_text",
                "bank_id": bank_id,
                "target_type": target_type
            })
            await event.send(event.plain_result(
                "📝 请发送该题库的别名文本。\n\n"
                "格式要求：\n"
                "- 每行对应一首曲目（顺序必须和题库顺序一致）\n"
                "- 别名之间用全角逗号（，）分隔\n"
                "- 例如：\n"
                "  无限天堂，IH\n"
                "  rip，安息\n\n"
                "发送“取消”取消导入。"
            ))
        else:
            set_upload_state(umo, {
                "step": "awaiting_alias_method",
                "bank_id": bank_id,
                "target_type": target_type
            })
            await event.send(event.plain_result(
                "请选择别名导入方式：\n"
                "1. 发送 Excel 文件（.xlsx）\n"
                "2. 发送纯文本（每行一个曲目，全角逗号分隔别名）\n\n"
                "请输入 1 或 2："
            ))
    elif choice == "2":
        clear_upload_state(umo)
        await event.send(event.plain_result("已取消导入。"))
    else:
        await event.send(event.plain_result("请输入 1 或 2。"))
        return True
    return True

async def handle_upload_alias_auto_confirm(event, user_id, umo, text, upload_state):
    """处理 awaiting_alias_auto_confirm 状态"""
    choice = text.strip()
    alias_map = upload_state.get("alias_map", {})
    
    if choice == "1":
        bank_id = upload_state["bank_id"]
        if not alias_map:
            clear_upload_state(umo)
            await event.send(event.plain_result("没有检测到别名数据。"))
            return True
        success, failed = import_custom_aliases(user_id, bank_id, alias_map)
        clear_upload_state(umo)
        await event.send(event.plain_result(
            f"✅ 别名导入完成！\n成功：{success} 个别名\n失败（重复或无效）：{failed} 个"
        ))
        return True
        
    elif choice == "2":
        bank_id = upload_state["bank_id"]
        clear_upload_state(umo)
        await event.send(event.plain_result(f"已跳过别名导入，稍后可使用 /导入别名 {bank_id} 手动导入。"))
        return True
        
    else:
        await event.send(event.plain_result("请输入 1 或 2。"))
        return True