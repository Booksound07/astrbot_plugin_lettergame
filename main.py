from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger
from astrbot.api.provider import LLMResponse
import astrbot.api.message_components as Comp
from astrbot.api.event import MessageChain
from astrbot.api import AstrBotConfig

from .core.game_manager import GameManager
from .core.song_bank import SongBankManager
from .core.alias_manager import (
    get_aliases,
    get_shared_aliases,
    add_alias_to_file,
    remove_alias_from_file,
    sync_aliases_for_title,
)
from .core.daily_manager import daily_record, save_daily_record, load_daily_record
from .core.search_engine import search_format_code, search_mask
from .core.query_parser import parse_query
from .core.song_info import show_song_info
from .core.pending_manager import (
    set_pending_query, get_pending_query, remove_pending_query,
    set_pending_alias, get_pending_alias, remove_pending_alias
)
from .core.board_builder import build_question_board
from .core.preset_manager import (
    get_preset, save_preset, add_preset, delete_preset,
    get_user_presets, preview_preset, update_preset_leaderboard
)
from .core.preset_parser import parse_preset_lines
from .core.preset_text_parser import parse_preset_text
from .core.preset_upload_manager import start_upload, cancel_upload, is_uploading
from .core.preset_edit_manager import (
    start_edit, is_editing, cancel_edit, process_edit_input
)

from .core.helpers import (
    require_group_at, get_game_state, is_admin, exact_command, extract_args,
    send_question_board, set_plugin_admins
)
from .core.constants import *
from .core import song_fetcher
from .core.alias_approval import AliasApprovalManager
from .core.utils import is_revealed, get_initial, normalize_search, is_blank
from .core.user_settings import (
    disable_bank, enable_bank,
    disable_custom_bank, get_disabled_custom_banks,
    get_disabled_banks, is_custom_bank_disabled, is_bank_disabled,
    get_query_mode, set_query_mode
)
from .core.user_name_cache import get_latest_name

from .core.custom_bank_manager import (
    get_banks_list, get_bank, delete_bank, rename_bank,
    create_bank, overwrite_bank, get_custom_songs,
    get_custom_aliases, add_custom_alias, remove_custom_alias,
    get_all_custom_aliases, get_custom_bank_id_by_song,
    import_custom_aliases, export_custom_aliases,
    parse_alias_text,
    share_bank, unshare_bank, get_shared_with,
    CUSTOM_BANK_DIR, _get_global_index
)
from .core.excel_parser import parse_excel
from .core.text_parser import parse_text
from .core.user_settings import (
    disable_custom_bank, enable_custom_bank,
    get_disabled_custom_banks, is_custom_bank_disabled
)

from .core.competition_settings import get_competition_state, set_competition_state, consume_competition_once
from .core.scoring import calculate_all_scores

from .core.guess_handler import GuessHandler
from .core.pending_handler import (
    init_handlers, handle_pending_query, handle_alias_choice
)

from .core.upload_handler import (
    get_upload_state, set_upload_state, clear_upload_state,
    is_upload_state_active,
    handle_upload_file, handle_upload_name, handle_upload_confirm,
    handle_upload_alias_choice, handle_alias_method,
    handle_import_file, handle_import_text,
    handle_del_confirm, handle_import_confirm,
    handle_upload_alias_auto_confirm
)

from .core.auto_listener import AutoListener

from .core.helpers import get_daily_seed_date, get_daily_expire_timestamp

import random
import re
import time
from pathlib import Path
import json
import os
import asyncio
import math

# 全局对象
gm = GameManager()
bank_manager = SongBankManager()
approval_mgr = AliasApprovalManager()
init_handlers(gm, bank_manager, approval_mgr)
# 插件临时文件目录
PLUGIN_TEMP_DIR = Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_lettergame" / "tmp"
PLUGIN_TEMP_DIR.mkdir(parents=True, exist_ok=True)

class LetterGame(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        # 加载配置
        self._config = config or {}
        self.plugin_admin_qq = self._config.get("plugin_admin_qq", [])
        set_plugin_admins(self.plugin_admin_qq)
        self.llm_matcher_provider_id = self._config.get(
            "llm_matcher_provider_id",
            ""
        ).strip()
        self.llm_prompt_custom = (
            self._config.get("llm_prompt_custom", "") or ""
        ).strip()
        from .core.llm_matcher import set_custom_prompt
        set_custom_prompt(self.llm_prompt_custom)
        logger.info(f"[LetterGame] 插件管理员配置: {self.plugin_admin_qq if self.plugin_admin_qq else '使用bot管理员'}")

        if not hasattr(self, "_letter_registered"):
            self._letter_registered = True
            global guess_handler
            guess_handler = GuessHandler(
                gm,
                bank_manager,
                context,
                self.llm_matcher_provider_id
            )
            self._pending_upload = {}
            self.auto_listener = AutoListener(
                gm,
                bank_manager,
                context,
                self.llm_matcher_provider_id
            )
            load_daily_record()
            
    def is_plugin_admin(self, event: AstrMessageEvent) -> bool:
        """
        检查用户是否为管理员。
        如果 plugin_admin_qq 配置为空列表，则使用 bot 管理员权限（event.is_admin()）。
        如果配置了具体 QQ 号列表，则只检查列表中是否包含该用户。
        """
        if event.is_admin():
            return True
        return str(event.get_sender_id()) in [str(x).strip() for x in self.plugin_admin_qq]

    # ---------------------- 消息拦截（处理题库上传、题库编辑、预设上传、待定选择、预设编辑） ----------------------
    @filter.event_message_type(
        filter.EventMessageType.ALL,
        priority=-100
    )
    async def handle_pending_select(self, event: AstrMessageEvent):

        from .core.constants import COMMAND_SET

        # 当前消息文本
        text = event.message_str.strip()

        # ============================================================
        # 0. 命令消息直接放行
        #
        # 这个判断必须放在所有状态处理之前！
        #
        # 因为本监听器 priority=-100，命令处理器可能已经先执行：
        #
        # /上传题库
        #   ↓
        # 命令处理器创建 upload_state
        #   ↓
        # 本监听器再次收到同一条消息
        #   ↓
        # 如果这里不提前 return，就会把 /上传题库 当成上传内容处理。
        #
        # COMMAND_SET 继续保留，用于下面“开字母自动答题监听”
        # 判断哪些消息不能当答案。
        # ============================================================

        # AstrBot 已经明确识别为命令

        command_text = text

        if command_text.startswith("/"):
            command_text = command_text[1:].strip()

        is_plugin_command = any(
            command_text == cmd
            or command_text.startswith(cmd + " ")
            for cmd in COMMAND_SET
        )

        if is_plugin_command:
            return

        # ============================================================
        # 0.5 群聊必须 @（或唤醒）；未 @ 的群消息直接放行，
        #     不参与任何状态处理（待定选择、上传、别名……）
        # ============================================================
        if require_group_at(event):
            return
        
        # ============================================================
        # 1. 基础信息
        #
        # 没有进行中的开字母时，群聊普通消息直接忽略。
        # 私聊消息则继续处理下面的上传、预设、别名等状态。
        # ============================================================
        user_id = event.get_sender_id()
        umo = event.unified_msg_origin
        key = event.unified_msg_origin
        
        # ============================================================
        # 2. 设置限开
        # ============================================================
        upload_state = get_upload_state(umo)
        
        if upload_state and upload_state.get("step") == "awaiting_open_limit":
                # 只有开局的人可以设置限开数量
                if str(event.get_sender_id()) != str(upload_state["sender_id"]):
                    await event.send(
                        event.plain_result(
                            "只有开启人可以设置限开数。"
                        )
                    )
                    return
                
                # 取消：连同已建好的对局一起撤掉
                if text == "取消":
                    cancel_group_id = upload_state.get("group_id")

                    clear_upload_state(umo)

                    if cancel_group_id:
                        gm.end_game(str(cancel_group_id))

                    await event.send(
                        event.plain_result("已取消本局开字母。")
                    )

                    event.call_llm = False
                    event.stop_event()
                    return

                try:
                    limit = int(text.strip())
                except ValueError:
                    await event.send(
                        event.plain_result(
                            "请输入整数！\n"
                            "输入 0 或正整数表示限制开字母数量。\n"
                            "输入负数表示不限开。"
                        )
                    )
                    event.call_llm = False
                    event.stop_event()
                    return

                # 负数 = 不限开
                # 0 = 限开0次，不能当成不限
                if limit < 0:
                    open_limit = None
                else:
                    open_limit = limit

                # 这些数据需要在清除状态前取出来
                group_id = upload_state["group_id"]
                used_bank_names = upload_state["used_bank_names"]
                sender_name = upload_state["sender_name"]

                # 正式开始游戏
                await self._start_pending_letter_game(
                    event,
                    umo,
                    open_limit
                )

                # 正式游戏已经创建，现在发送题目板
                st = gm.get_state(group_id)
                range_text = "、".join(used_bank_names)

                if open_limit is None:
                    limit_text = "不限"
                else:
                    limit_text = str(open_limit)

                extra = (
                    f"开启人：{sender_name}\n"
                    f"题目范围：{range_text}\n"
                    f"限开字母：{limit_text}\n"
                    "使用 /开 或 /open 字母 开字母\n"
                    "使用 /猜 或 /guess 曲名 进行作答\n"
                    "使用 /tip 获取提示"
                )

                await send_question_board(event, st, extra)

                event.call_llm = False
                event.stop_event()
                return

        # ============================================================
        # 3. 处理自定义题库上传
        # ============================================================
        upload_state = get_upload_state(umo)

        if upload_state:

            if (
                text == "取消"
                and upload_state["step"] in [
                    "awaiting_file",
                    "awaiting_name",
                    "awaiting_confirm",
                    "awaiting_alias_auto_confirm",
                    "awaiting_alias_choice",
                    "awaiting_alias_method",
                    "awaiting_import_file",
                    "awaiting_import_text",
                    "awaiting_del_confirm",
                    "awaiting_import_confirm",
                    "awaiting_open_limit",
                ]
            ):
                clear_upload_state(umo)

                await event.send(
                    event.plain_result("已取消操作。")
                )

                event.call_llm = False
                event.stop_event()
                return

            handled = False

            if upload_state["step"] == "awaiting_file":

                # 如果当前消息本身包含文件，
                # 正常情况下已经被 priority=100 的文件监听器处理。
                has_file = any(
                    comp.type == "File"
                    for comp in event.message_obj.message
                )

                if has_file:
                    return

                # 没有文件 → 继续走原来的 handle_upload_file，
                # 让它处理纯文本上传
                handled = await handle_upload_file(
                    event,
                    user_id,
                    umo,
                    text,
                    upload_state
                )

                if handled:
                    event.call_llm = False
                    event.stop_event()
                    return

            elif upload_state["step"] == "awaiting_name":

                handled = await handle_upload_name(
                    event,
                    user_id,
                    umo,
                    text,
                    upload_state
                )

            elif upload_state["step"] == "awaiting_confirm":

                handled = await handle_upload_confirm(
                    event,
                    user_id,
                    umo,
                    text,
                    upload_state
                )

            elif upload_state["step"] == "awaiting_alias_auto_confirm":

                handled = await handle_upload_alias_auto_confirm(
                    event,
                    user_id,
                    umo,
                    text,
                    upload_state
                )

            elif upload_state["step"] == "awaiting_alias_choice":

                handled = await handle_upload_alias_choice(
                    event,
                    user_id,
                    umo,
                    text,
                    upload_state
                )

            elif upload_state["step"] == "awaiting_alias_method":

                handled = await handle_alias_method(
                    event,
                    user_id,
                    umo,
                    text,
                    upload_state
                )

            elif upload_state["step"] == "awaiting_import_text":

                handled = await handle_import_text(
                    event,
                    user_id,
                    umo,
                    text,
                    upload_state
                )

            elif upload_state["step"] == "awaiting_del_confirm":

                handled = await handle_del_confirm(
                    event,
                    user_id,
                    umo,
                    text,
                    upload_state
                )

            elif upload_state["step"] == "awaiting_import_confirm":

                handled = await handle_import_confirm(
                    event,
                    user_id,
                    umo,
                    text,
                    upload_state
                )

            else:
                clear_upload_state(umo)

                await event.send(
                    event.plain_result(
                        "状态错误，已重置。请重新使用 /上传题库 进行操作。"
                    )
                )

                handled = True

            if handled:
                event.call_llm = False
                event.stop_event()
                return

        # ============================================================
        # 4. 处理加别名/删别名选择
        # ============================================================
        handled = await handle_alias_choice(
            event,
            text,
            key,
            "add"
        )

        if handled:
            event.call_llm = False
            event.stop_event()
            return

        handled = await handle_alias_choice(
            event,
            text,
            key,
            "delete"
        )

        if handled:
            event.call_llm = False
            event.stop_event()
            return

        # ============================================================
        # 5. 处理预设上传（私聊）
        # ============================================================
        if event.is_private_chat() and is_uploading(user_id):

            lines = parse_preset_text(text)

            if not lines:
                cancel_upload(user_id)

                await event.send(
                    event.plain_result(
                        "上传失败！\n\n"
                        "未检测到合法的开字母题格式。\n"
                        "请检查序号是否存在。\n\n"
                        "重新使用 /letterpreset 后再上传。"
                    )
                )

                event.call_llm = False
                event.stop_event()
                return

            preset_id = add_preset(
                lines,
                uploader=user_id
            )

            cancel_upload(user_id)

            await event.send(
                event.plain_result(
                    f"上传成功！\n\n"
                    f"编号：{preset_id}\n\n"
                    f"使用 /letterload {preset_id} 即可开始。\n"
                    f"可以使用/mypreset对题目权限进行编辑"
                )
            )

            event.call_llm = False
            event.stop_event()
            return

        # ============================================================
        # 6. 处理待定选择（/查曲 多选）
        # ============================================================
        handled = await handle_pending_query(event, text, key)

        if handled:
            event.call_llm = False
            event.stop_event()
            return

        # ============================================================
        # 7. 处理预设编辑（私聊）
        # ============================================================
        if event.is_private_chat():

            handled, reply = await process_edit_input(
                user_id,
                text,
                event
            )

            if handled:
                if reply:
                    await event.send(
                        event.plain_result(reply)
                    )

                event.call_llm = False
                event.stop_event()
                return
        
    # ============================================================
    # 开字母自动监听
    # 优先级 -200，作为兜底处理
    # ============================================================
    @filter.event_message_type(
        filter.EventMessageType.ALL,
        priority=-200
    )
    async def handle_auto_guess(self, event: AstrMessageEvent):
        """开字母期间自动判对，只判对不判错"""

        group_id = event.get_group_id()

        if not group_id:
            group_id = f"private_{event.get_sender_id()}"

        st = gm.get_state(group_id)

        if not st:
            return

        # 判断是否是命令：使用 COMMAND_SET
        from .core.constants import COMMAND_SET

        text = event.message_str.strip()
        is_command = False

        for cmd in COMMAND_SET:
            if text == cmd or text.startswith(cmd + " "):
                is_command = True
                break

        if is_command:
            return

        found, _ = await self.auto_listener.handle_message(
            event,
            st
        )

        # 开字母期间，普通消息不交给 LLM
        event.call_llm = False

        # 明确以数字开头的作答消息（「11 atrr」「1. xxx」，以及「22085」这种
        # 答案本身是纯数字的情况）：不管答对答错都到此为止，
        # 避免答错时事件继续往下走被别的插件接话。
        # 不以数字开头的普通聊天不受影响，仍交给其他插件。
        looks_like_answer = re.match(
            r"^\d+(?:[.、．。)\]）]|\s|$)",
            text
        ) is not None

        if found or looks_like_answer:
            event.stop_event()
            return

        # 没猜中：
        # 不 stop_event，让其他插件仍有机会处理
        # 但 call_llm=False，防止进入默认 LLM
        
    # ============================================================
    # 普通群聊消息
    # 优先级 -300，作为所有开字母逻辑之后的兜底
    # ============================================================
    @filter.event_message_type(
        filter.EventMessageType.GROUP_MESSAGE,
        priority=-300
    )
    async def handle_normal_group_message(self, event: AstrMessageEvent):
        """普通群聊消息，不参与插件处理"""
        return
        
    # ---------------------- 文件上传监听 ----------------------
    @filter.event_message_type(
        filter.EventMessageType.ALL,
        priority=100
    )
    async def handle_file_upload_event(self, event: AstrMessageEvent):

        # 只处理包含 File 消息段的消息
        has_file = any(
            comp.type == "File"
            for comp in event.message_obj.message
        )

        if not has_file:
            return

        user_id = str(event.get_sender_id())
        umo = event.unified_msg_origin

        upload_state = get_upload_state(umo)

        # 没有进行中的上传操作
        if not upload_state:
            return

        step = upload_state.get("step")

        # ============================================================
        # 1. 上传自定义题库 Excel
        # ============================================================
        if step == "awaiting_file":

            handled = await handle_upload_file(
                event,
                user_id,
                umo,
                event.message_str,
                upload_state
            )

        # ============================================================
        # 2. 导入别名 Excel
        # ============================================================
        elif step == "awaiting_import_file":

            handled = await handle_import_file(
                event,
                user_id,
                umo,
                event.message_str,
                upload_state
            )

        else:
            # 当前虽然有上传状态，但不是文件上传阶段
            return

        if handled:
            event.call_llm = False
            event.stop_event()
            return
        
    async def _start_pending_letter_game(
        self,
        event,
        umo: str,
        open_limit: int | None
    ):
        upload_state = get_upload_state(umo)

        # 状态不存在，说明已经被处理过或取消了
        if not upload_state:
            return

        if upload_state.get("step") != "awaiting_open_limit":
            return

        group_id = upload_state["group_id"]
        puzzles = upload_state["puzzles"]
        format_code_counts = upload_state["format_code_counts"]
        preset_id = upload_state.get("preset_id")

        # 清除等待状态
        clear_upload_state(umo)

        # 正式创建游戏
        if preset_id is not None:
            gm.new_game(
                group_id,
                puzzles,
                preset_id=preset_id
            )
        else:
            gm.new_game(
                group_id,
                puzzles
            )

        # 写入限开数量
        st = gm.get_state(group_id)
        st["open_limit"] = open_limit
        
        # 标记是否来自预设
        st["from_preset"] = preset_id is not None

        # 写入格式码统计
        st["format_code_counts"] = format_code_counts
        gm.save()

        # ===== 比赛模式 =====
        state = get_competition_state(group_id)
        enabled = state.get("enabled", False)
        once = state.get("once", False)

        if enabled or once:
            gm.set_competition_mode(group_id, True)

            if once:
                consume_competition_once(group_id)
                await event.send(
                    event.plain_result("📢 比赛模式已开启（本次生效）")
                )
            else:
                await event.send(
                    event.plain_result("📢 比赛模式已开启")
                )
        else:
            gm.set_competition_mode(group_id, False)
            
    async def _open_limit_timeout(
        self,
        event: AstrMessageEvent,
        umo: str
    ):
        await asyncio.sleep(60)

        from astrbot.api import logger
        import astrbot.api.message_components as Comp

        logger.info(
            f"[开字母] 限开设置超时任务触发，UMO={umo}"
        )

        # 检查等待状态是否还存在
        upload_state = get_upload_state(umo)

        # 60 秒内已经输入过、取消过，或者状态不存在
        if not upload_state:
            logger.info("[开字母] 限开等待状态已不存在，取消超时处理")
            return

        if upload_state.get("step") != "awaiting_open_limit":
            logger.info("[开字母] 当前状态不是 awaiting_open_limit，取消超时处理")
            return

        # ===== 读取暂存数据 =====
        group_id = upload_state["group_id"]
        puzzles = upload_state["puzzles"]
        format_code_counts = upload_state["format_code_counts"]
        used_bank_names = upload_state["used_bank_names"]
        sender_name = upload_state["sender_name"]
        preset_id = upload_state.get("preset_id")

        # ===== 清除等待状态 =====
        clear_upload_state(umo)

        # ===== 正式创建游戏 =====
        if preset_id is not None:
            gm.new_game(
                group_id,
                puzzles,
                preset_id=preset_id
            )
        else:
            gm.new_game(
                group_id,
                puzzles
            )

        st = gm.get_state(group_id)

        # 超时 = 不限开
        st["open_limit"] = None

        # 写入格式码统计
        st["format_code_counts"] = format_code_counts

        gm.save()

        # ===== 比赛模式 =====
        state = get_competition_state(group_id)
        enabled = state.get("enabled", False)
        once = state.get("once", False)

        if enabled or once:
            gm.set_competition_mode(group_id, True)

            if once:
                consume_competition_once(group_id)

                await event.send(
                    event.plain_result("📢 比赛模式已开启（本次生效）")
                )
            else:
                await event.send(
                    event.plain_result("📢 比赛模式已开启")
                )
        else:
            gm.set_competition_mode(group_id, False)

        # ===== 超时提示 =====
        await event.send(
            event.plain_result(
                    "限开字母数设置超时，本局将按不限开开始。"
            )
        )

        # ===== 准备题目板 =====
        st = gm.get_state(group_id)

        range_text = "、".join(used_bank_names)

        extra = (
            f"开启人：{sender_name}\n"
            f"题目范围：{range_text}\n"
            "使用 /开 或 /open 字母 开字母\n"
            "使用 /猜 或 /guess 曲名 进行作答\n"
            "使用 /tip 获取提示"
        )

        # ===== 根据题目数量决定发送文字还是图片 =====
        question_count = sum(
            1
            for q in st["questions"]
            if q.get("type") != "decor"
        )

        if question_count > 15:
            # 先发送额外文字
            await event.send(
                event.plain_result(extra)
            )

            # 生成题目板图片
            from .board_image_renderer import render_board_image

            img_path = render_board_image(
                st["questions"],
                st.get("open_chars", [])
            )

            # 发送图片
            await event.send(
                event.image_result(img_path)
            )

        else:
            # 15题及以下，发送文字题板
            board = build_question_board(st)

            if extra:
                board = extra + "\n" + board

            await event.send(
                event.plain_result(board)
            )

        logger.info(
            f"[开字母] 限开设置超时处理完成，群组={group_id}"
        )

    # ---------------------- 帮助命令 ----------------------
    @filter.command("letterhelp", alias={"开字母帮助"})
    async def letterhelp(self, event: AstrMessageEvent):
        from .core.help_image_renderer import render_help_image
        image_path = render_help_image()
        await event.send(event.image_result(image_path))

    # ---------------------- 开始游戏 ----------------------
    @filter.command("letter", alias={"开始开字母"})
    async def start(self, event: AstrMessageEvent, args: str = ""):
        bank_manager.auto_reload()

        args = args.strip().split()
        n = DEFAULT_QUESTION_COUNT

        if len(args) >= 1:
            if args[0].isdigit():
                n = int(args[0])
            else:
                await event.send(event.plain_result("用法：/letter [题目数量]"))
                return

        group_id = event.get_group_id()
        if not group_id:
            group_id = f"private_{event.get_sender_id()}"
        if gm.get_state(group_id):
            await event.send(event.plain_result("当前已有进行中的开字母游戏，请先结束再开始新的。"))
            return

        sender_id = event.get_sender_id()
        disabled_banks = get_disabled_banks(sender_id)

        pool = []
        used_bank_names = []
        
        for bank_name in bank_manager.get_bank_names():
            if bank_name in disabled_banks:
                continue
            
            used_bank_names.append(bank_name)
            
            pool.extend([
                song for song in bank_manager.get_bank(bank_name)
                if song.get("is_standard", False)
            ])
            
        custom_banks = get_banks_list(sender_id)
        disabled_custom = get_disabled_custom_banks(sender_id)
        for bank in custom_banks:
            if bank["id"] in disabled_custom:
                continue
            bank_data = get_bank(sender_id, bank["id"])
            if bank_data:
                used_bank_names.append(bank["name"])
                for song in bank_data["songs"]:
                    if "format_code" not in song:
                        title = song.get("title", "")
                        song["format_code"] = "-".join(
                            str(len(w)) for w in title.split()
                        )
                    pool.append(song)

        if not pool:
            await event.send(event.plain_result("所有题库均已禁用，无法开始游戏。请使用 /启用 [题库名] 启用至少一个题库。"))
            return

        seen_titles = set()
        selected = []
        shuffled = random.sample(pool, min(len(pool), n * 2))
        for entry in shuffled:
            if len(selected) >= n:
                break
            title = entry["title"]
            if title not in seen_titles:
                seen_titles.add(title)
                selected.append(entry)

        puzzles = [
            {
                "entry": entry,
                "mask": "".join(
                    " " if c.isspace() else "*"
                    for c in entry["title"]
                ),
                "solved": False
            }
            for entry in selected
        ]

        gm.new_game(group_id, puzzles)

        # 统计格式码出现次数（用于难度倍率）
        # 注意：要基于整个题库池统计，不是基于本局抽出的题目
        format_code_counts = {}
        for song in pool:
            fc = song.get("format_code", "")
            if fc:
                format_code_counts[fc] = format_code_counts.get(fc, 0) + 1

        # 暂存本局数据，等待开启者输入限开字母数
        umo = event.unified_msg_origin

        set_upload_state(umo, {
            "step": "awaiting_open_limit",
            "sender_id": sender_id,
            "group_id": group_id,
            "puzzles": puzzles,
            "format_code_counts": format_code_counts,
            "used_bank_names": used_bank_names,
            "sender_name": event.get_sender_name() or sender_id,
            "expire_at": time.time() + 60,
        })

        await event.send(
            event.plain_result(
                "请输入本局开字母的限开数：\n"
                "正整数：限制最多开多少次\n"
                "0：禁止开字母\n"
                "负数：不限次数\n"
                "60 秒内未输入则默认不限次数。\n"
                "输入“取消”取消本局开字母。"
            )
        )

        # 60 秒后如果仍未设置，则按不限开开始
        asyncio.create_task(
            self._open_limit_timeout(event, umo)
        )

    # ---------------------- 阻塞 LLM 回复（游戏进行中） ----------------------
    @filter.on_agent_done(priority=1)
    async def block_agent_when_game_running(self, event, run_context, resp: LLMResponse):
        group_id = event.get_group_id()
        if not group_id:
            return
        if gm.get_state(group_id):
            resp.completion_text = ""
            
    @filter.on_llm_response(priority=1)
    async def block_llm_when_game_running(self, event, resp: LLMResponse):
        group_id = event.get_group_id()
        if not group_id:
            return
        if gm.get_state(group_id):
            resp.completion_text = ""

    # ---------------------- 开字母 ----------------------
    @filter.command("open", alias={"开"})
    async def open_char(self, event: AstrMessageEvent, ch: str):
        # 检查参数
        if not ch or len(ch.strip()) == 0:
            await event.send(event.plain_result("用法：/开 [字母] 或 /open [字母]"))
            return

        group_id, st = get_game_state(event, gm)
        if not st:
            await event.send(event.plain_result("当前没有进行中的开字母。"))
            return

        # ===== 每日挑战超时检测 =====
        if st.get("daily_expire_at") and time.time() > st.get("daily_expire_at"):
            for q in st["questions"]:
                if q.get("type") != "decor":
                    q["mask"] = q["entry"]["title"]
            await send_question_board(event, st, "每日挑战已超时，游戏已结束，全部答案如下：")
            gm.end_game(group_id)
            return

        # ===== 每日挑战限开检测 =====
        daily_limit = st.get("daily_limit") or 0
        if daily_limit > 0:
            current_open = len(st.get("open_chars", []))
            if current_open >= daily_limit:
                await event.send(event.plain_result("开字母次数已用完。"))
                return
            
        # ===== 普通开字母限开检测 =====
        if st.get("open_limit") is not None:
            current_open = len(st.get("open_chars", []))
            if current_open >= st["open_limit"]:
                await event.send(
                    event.plain_result("开字母次数已用完。")
                )
                return

        if len(ch) != 1:
            await event.send(event.plain_result("只能开一个字符！"))
            return

        if "open_chars" not in st:
            st["open_chars"] = []
        # 重复开检测
        if ch.lower() in [x.lower() for x in st["open_chars"]]:
            await event.send(event.plain_result(f"“{ch}”已经开过了。"))
            return

        st["open_chars"].append(ch)

        if st:
            if gm.get_first_open_time(group_id) is None:
                gm.set_first_open_time(group_id, time.time())

        for q in st["questions"]:
            if q.get("type") == "decor":
                continue
            title = q["entry"]["title"]
            new_mask = "".join(
                (" " if is_blank(c) else c) if is_revealed(c, st["open_chars"]) else m
                for c, m in zip(title, q["mask"])
            )
            q["mask"] = new_mask
            if all(is_revealed(c, st["open_chars"]) for c in title):
                q["solved"] = True

        gm.save()
        await send_question_board(event, st, "")

    # ---------------------- 提示 ----------------------
    @filter.command("tip", alias={"提示"})
    async def tip(self, event: AstrMessageEvent):
        group_id, st = get_game_state(event, gm)
        if not st:
            await event.send(event.plain_result("当前没有进行中的开字母。"))
            return

        # ===== 每日挑战超时检测 =====
        if st.get("daily_expire_at") and time.time() > st.get("daily_expire_at"):
            for q in st["questions"]:
                if q.get("type") != "decor":
                    q["mask"] = q["entry"]["title"]
            await send_question_board(event, st, "每日挑战已超时，游戏已结束，全部答案如下：")
            gm.end_game(group_id)
            return

        # ===== 每日挑战限开检测（tip 也消耗限开） =====
        daily_limit = st.get("daily_limit") or 0
        if daily_limit > 0:
            current_open = len(st.get("open_chars", []))
            if current_open >= daily_limit:
                await event.send(event.plain_result("开字母次数已用完。"))
                return
        # ===== 普通开字母限开检测（tip 也消耗限开） =====
        if st.get("open_limit") is not None:
            current_open = len(st.get("open_chars", []))
            if current_open >= st["open_limit"]:
                await event.send(event.plain_result("开字母次数已用完。"))
                return

        unsolved = [q for q in st["questions"] if q.get("type") != "decor" and not q.get("solved", False)]
        if not unsolved:
            await event.send(event.plain_result("所有题目已经完成！"))
            return

        pick = random.choice(unsolved)
        orig = pick["entry"]["title"]
        opened = {x.lower() for x in st.get("open_chars", [])}
        candidates = []

        for c in orig:
            if c.isalpha() and ord(c) < 128:
                if c.lower() not in opened:
                    candidates.append(c.lower())
                continue
            initial = get_initial(c)
            if initial and initial not in opened:
                candidates.append(initial)
            elif not initial and not c.isspace() and c not in opened:
                candidates.append(c)

        if not candidates:
            await event.send(event.plain_result("当前题目已全部揭开。"))
            return

        ch = random.choice(candidates)

        # ===== 先执行开字母（消耗限开） =====
        if "open_chars" not in st:
            st["open_chars"] = []
        if ch.lower() not in [x.lower() for x in st["open_chars"]]:
            st["open_chars"].append(ch)

            # 记录首次操作
            if st:
                if gm.get_first_open_time(group_id) is None:
                    gm.set_first_open_time(group_id, time.time())

            # 更新掩码
            for q in st["questions"]:
                if q.get("type") == "decor":
                    continue
                title = q["entry"]["title"]
                new_mask = "".join(
                    (" " if is_blank(c) else c) if is_revealed(c, st["open_chars"]) else m
                    for c, m in zip(title, q["mask"])
                )
                q["mask"] = new_mask
                if all(is_revealed(c, st["open_chars"]) for c in title):
                    q["solved"] = True

            # ===== 比赛模式：tip 惩罚累加 =====
            gm.increment_tip_count(group_id)

            gm.save()
            await send_question_board(event, st, "")
            await event.send(event.plain_result(f"提示揭开了字母：{ch}"))
        else:
            # 理论上不会发生，但以防万一
            await event.send(event.plain_result("提示失败，请重试。"))

    # ---------------------- 结束游戏 ----------------------
    @filter.command("end", alias={"结束", "结束开字母"})
    async def end_game(self, event: AstrMessageEvent, args: str = ""):
        if args.strip():
            return
        if not exact_command(event, "end", "结束", "结束开字母"):
            return

        group_id, st = get_game_state(event, gm)
        if not st:
            await event.send(event.plain_result("当前没有游戏。"))
            return
        
        # ===== 每日挑战超时检测（如果超时，直接用超时文案） =====
        if st.get("daily_expire_at") and time.time() > st.get("daily_expire_at"):
            for q in st["questions"]:
                if q.get("type") != "decor":
                    q["mask"] = q["entry"]["title"]
            await send_question_board(event, st, "每日挑战已超时，游戏已结束，全部答案如下：")
            gm.end_game(group_id)
            return

        players = None
        preset_id = None
        if gm.is_competition_mode(group_id):
            players = gm.get_players(group_id)
        preset_id = gm.get_preset_id(group_id)

        gm.end_game(group_id)
        extra = "游戏已结束，全部答案如下："
        for q in st["questions"]:
            if q.get("type") != "decor":
                q["mask"] = q["entry"]["title"]
        await send_question_board(event, st, extra)

        # 检查是否为预设，记录首次通关（独立于 players）
        if preset_id is not None:
            # 无需 import，顶部已有  
            user_id = event.get_sender_id()
            if players:
                scores = calculate_all_scores(players)
                total_score = scores.get(user_id, 0)
                if not gm.is_competition_mode(group_id):
                    total_score = 0
                if update_preset_leaderboard(
                        preset_id,
                        group_id,
                        user_id,
                        total_score,
                        event.get_sender_name()
                    ):
                    if total_score > 0:
                        await event.send(event.plain_result(f"首次通关！得分 {total_score} 已计入预设排行榜。"))
                    else:
                        await event.send(event.plain_result("非比赛模式仅记录通关情况。"))
                else:
                    await event.send(event.plain_result("你已经看过答案了！本次得分不计入排行榜。"))
            else:
                # 没有玩家数据时，只记录一个 0 分
                update_preset_leaderboard(
                    preset_id,
                    group_id,
                    user_id,
                    0,
                    event.get_sender_name()
                )
                await event.send(event.plain_result("已记录通关情况。"))

        if players:
            scores = calculate_all_scores(players)
            ranking = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            lines = ["🏆 排行榜："]
            for idx, (uid, score) in enumerate(ranking, 1):
                name = players[uid].get("name", uid)
                lines.append(f"#{idx}  {name}  {score}")
            await event.send(event.plain_result("\n".join(lines)))

    # ---------------------- 每日挑战 ----------------------
    @filter.command("daily", alias={"每日挑战"})
    async def daily(self, event: AstrMessageEvent, args: str = ""):
        if args.strip():
            args = args.strip()
        else:
            args = ""

        # ===== 超时检测：如果当前有游戏且是每日挑战且已过期，直接结束 =====
        group_id, st = get_game_state(event, gm)
        if st and st.get("daily_expire_at") and time.time() > st.get("daily_expire_at"):
            for q in st["questions"]:
                if q.get("type") != "decor":
                    q["mask"] = q["entry"]["title"]
            await send_question_board(event, st, "每日挑战已超时，游戏已结束，全部答案如下：")
            gm.end_game(group_id)
            return

        if st:
            await event.send(event.plain_result("当前已有进行中的开字母游戏，请先结束再开始新的。"))
            return

        # ===== 确定种子日期（4点前后） =====
        import datetime
        import hashlib
        seed_date = get_daily_seed_date()
        today_str = seed_date.strftime("%Y%m%d")
        group_id_str = str(group_id)

        # ===== 解析题库参数 =====
        bank_name_input = args.strip().lower() if args else ""
        
        # 获取所有内置题库名
        all_bank_names = bank_manager.get_bank_names()
        
        # 确定使用的题库
        if bank_name_input:
            # 用户指定了题库名，检查是否存在
            if bank_name_input not in all_bank_names:
                await event.send(event.plain_result(f"不存在题库：{bank_name_input}"))
                return
            target_bank = bank_name_input
            display_name = target_bank
        else:
            target_bank = "all"
            display_name = "全部题库"

        # ===== 检查今日挑战是否已经做过 =====
        daily_key = f"{group_id_str}_{target_bank}"
        if daily_record.get(daily_key) == today_str:
            await event.send(event.plain_result(f"本群今日的 {display_name} 每日挑战已经开启过了，请明天再来。"))
            return

        bank_manager.auto_reload()
        seed = int(hashlib.md5((today_str + group_id_str + target_bank).encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        # ===== 获取曲目池 =====
        if target_bank == "all":
            all_songs = [s for s in bank_manager.get_all_songs() if s.get("is_standard", False)]
        else:
            all_songs = [s for s in bank_manager.get_bank(target_bank) if s.get("is_standard", False)]

        if not all_songs:
            await event.send(event.plain_result("该题库为空，无法开始每日挑战。"))
            return

        selected = rng.sample(all_songs, min(DEFAULT_QUESTION_COUNT, len(all_songs)))
        puzzles = [
            {
                "entry": entry,
                "mask": "".join(
                    " " if c.isspace() else "*"
                    for c in entry["title"]
                ),
                "solved": False
            }
            for entry in selected
        ]

        # ===== 计算格式码快照（基于当前题库池） =====
        snapshot = {}
        for song in all_songs:
            fc = song.get("format_code", "")
            if fc:
                snapshot[fc] = snapshot.get(fc, 0) + 1

        # ===== 计算本组题目的难度总分（四项评分） =====
        from .core.daily_scoring import calc_daily_total, estimate_daily_limit

        def _get_aliases_for_entry(entry):
            bank = entry.get("bank", "")
            title = entry.get("title", "")
            if not bank or not title:
                return []
            return get_aliases(bank, title)

        total_score, _breakdown = calc_daily_total(
            puzzles,
            snapshot,
            _get_aliases_for_entry
        )

        # ===== 根据总分查表限开数 =====
        daily_limit = estimate_daily_limit(total_score)

        # ===== 创建游戏 =====
        gm.new_game(group_id_str, puzzles)
        st = gm.get_state(group_id_str)

        # ===== 比赛模式设置 =====
        state = get_competition_state(group_id_str)
        enabled = state.get("enabled", False)
        once = state.get("once", False)

        if enabled or once:
            gm.set_competition_mode(group_id_str, True)
            if once:
                consume_competition_once(group_id_str)
                await event.send(event.plain_result("📢 比赛模式已开启（本次生效）"))
            else:
                await event.send(event.plain_result("📢 比赛模式已开启"))
        else:
            gm.set_competition_mode(group_id_str, False)

        # 存储每日挑战专用字段
        st["daily_limit"] = daily_limit
        st["daily_expire_at"] = get_daily_expire_timestamp()
        st["daily_snapshot"] = snapshot
        st["format_code_counts"] = snapshot
        st["daily_seed_date"] = today_str
        st["daily_bank_name"] = display_name
        st["format_code_counts"] = snapshot
        gm.save()

        daily_record[daily_key] = today_str
        save_daily_record()

        # ===== 发送题面 =====
        if target_bank == "all":
            range_text = "、".join(all_bank_names)
        else:
            range_text = display_name

        extra = (
            f"每日挑战：{display_name}\n"
            f"题目范围：{range_text}\n"
            "使用 /开 或 /open 字母 开字母\n"
            "使用 /猜 或 /guess 曲名 进行作答\n"
            "使用 /tip 获取提示\n"
            f"难度评分：{math.ceil(total_score)}，限开{daily_limit}个字母"
        )
        await send_question_board(event, st, extra)

    # ---------------------- 上传预设 ----------------------
    @filter.command("letterpreset", alias={"上传预设"})
    async def letterpreset(self, event: AstrMessageEvent):
        if event.get_group_id():
            await event.send(event.plain_result("请在私聊中使用此命令。"))
            return
        user_id = event.get_sender_id()
        start_upload(user_id)
        await event.send(event.plain_result(
            "请发送整套开字母题。\n\n格式：\n序号+题目\n序号后允许有空格。\n\n例如：\n+1. 这是一条装饰行\n2. Infinity Heaven\n3. Retribution\n4. ^_^\n\n装饰行请在序号前加 '+'。\n例如：\n+1. 这是一条装饰行\n+2. ^_^\n\n无需手动输入 *，请务必直接输入原文。\nBot 会自动生成开字母题面。\n\n发送整套内容即可上传。"
        ))

    # ---------------------- 加载预设 ----------------------
    @filter.command("letterload", alias={"加载预设"})
    async def letterload(self, event: AstrMessageEvent):
        parts = event.message_str.strip().split()
        if len(parts) < 2:
            await event.send(event.plain_result("用法：/letterload [编号]"))
            return
        try:
            preset_id = int(parts[1])
        except:
            await event.send(event.plain_result("编号必须是数字。"))
            return

        preset = get_preset(preset_id)
        if preset is None:
            await event.send(event.plain_result("不存在这个预设。"))
            return

        group_id = event.get_group_id()
        if not group_id:
            group_id = f"private_{event.get_sender_id()}"
        allowed_groups = preset["allowed_groups"]
        if allowed_groups and group_id not in allowed_groups:
            await event.send(event.plain_result("该群无权限开启该题目。"))
            return

        sender_id = event.get_sender_id()
        uploader = preset["uploader"]
        allowed_users = preset["allowed_users"]

        if allowed_users is None:
            pass
        elif allowed_users == []:
            if sender_id != uploader:
                await event.send(event.plain_result("权限不足，无法开启题目。"))
                return
        else:
            if sender_id != uploader and sender_id not in allowed_users:
                await event.send(event.plain_result("权限不足，无法开启题目。"))
                return

        if gm.get_state(group_id):
            await event.send(event.plain_result("当前已有进行中的开字母游戏。"))
            return

        puzzles = parse_preset_lines(preset["lines"])

        set_upload_state(event.unified_msg_origin, {
            "step": "awaiting_open_limit",
            "sender_id": str(sender_id),
            "group_id": group_id,
            "puzzles": puzzles,
            "format_code_counts": {},
            "used_bank_names": ["来自预设"] ,
            "sender_name": event.get_sender_name() or str(sender_id),
            "preset_id": preset_id,
            "expire_at": time.time() + 60,
        })

        await event.send(event.plain_result(
            "请输入本局开字母的限开数：\n"
            "正整数：限制最多开多少次\n"
            "0：禁止开字母\n"
            "负数：不限次数\n"
            "60 秒内未输入则默认不限次数。\n"
            "输入“取消”取消本局开字母。"
        ))

        asyncio.create_task(
            self._open_limit_timeout(
                event,
                event.unified_msg_origin
            )
        )
        
        

    # ---------------------- 我的预设 ----------------------
    @filter.command("mypreset", alias={"我的预设"})
    async def mypreset(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()
        presets = get_user_presets(user_id)
        if not presets:
            await event.send(event.plain_result("你还没有上传过题目。"))
            return

        text = "你的题目：\n\n"
        for i, item in enumerate(presets, 1):
            text += f"{i}. #{item['id']}\n"
        text += "\n回复序号而非题号进入编辑。"

        start_edit(user_id, [item["id"] for item in presets])
        await event.send(event.plain_result(text))
        
    # ---------------------- 自定义题库管理 ----------------------
    @filter.command("uploadbank", alias={"上传题库"})
    async def upload_bank(self, event: AstrMessageEvent):
        """上传自定义题库"""
        if event.get_group_id():
            await event.send(event.plain_result("请私聊使用此命令上传题库。"))
            return

        user_id = str(event.get_sender_id())
        umo = event.unified_msg_origin

        if get_upload_state(umo):
            await event.send(event.plain_result("您已有进行中的上传操作，请继续或发送“取消”取消。"))
            return

        msg = (
            "📤 上传自定义题库\n\n"
            "请按以下格式准备 Excel 文件或文本内容\n\n"
            "若准备了 Excel 文件，请注意以下事项：\n"
            "- 第一行为表头\n"
            "- 必须包含以下两列（列名必须完全一致）：\n"
            "  · 曲名：歌曲/题目名称\n"
            "  · 是否是标准曲名：填 1 或 true 表示标准曲名，填 0 或 false 表示非标准\n"
            "- 允许包含别名列（可选）\n\n"
            "若仅有文本内容，请注意以下事项：\n"
            "- 每行只能包含一项\n"
            "- 所有项默认为标准曲名\n\n"
            "上传后题库仅限你自己使用：\n"
            "✅ /letter 会包含你的自定义题库\n"
            "✅ /查询 和 /查曲 会搜索你的自定义题库\n"
            "❌ /daily 不会使用自定义题库\n\n"
            "发送 Excel 文件或文本开始上传，或发送“取消”取消本次操作。"
        )

        set_upload_state(umo, {
            "step": "awaiting_file",
            "title_column": "曲名",
            "standard_column": "是否是标准曲名",
            "is_excel": False,
            "songs": None
        })

        await event.send(event.plain_result(msg))

    @filter.command("mybanks", alias={"我的题库"})
    async def mybanks(self, event: AstrMessageEvent):
        """查看我的自定义题库列表"""
        user_id = str(event.get_sender_id())
        banks = get_banks_list(user_id)
        if not banks:
            await event.send(event.plain_result("📚 你的自定义题库（共 0 个）\n\n还没有自定义题库。使用 /uploadbank 上传第一个吧！"))
            return

        lines = [f"📚 你的题库（共 {len(banks)} 个）\n"]
        for bank in banks:
            upload_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(bank["upload_time"]))
            shared_mark = " （来自他人共享）" if bank.get("is_shared") else ""
            lines.append(f"{bank['id']}  {bank['name']}  {bank['song_count']} 首  {upload_time}{shared_mark}")
            lines.append(f"   上传者：{bank['uploader']}")

        lines.append("\n使用 /改名 [自定义题库ID] [新名称] 修改题库名称（仅创建者）")
        lines.append("使用 /删除题库 [自定义题库ID] 删除题库（仅创建者）")
        lines.append("使用 /共享题库 [用户QQ号] [自定义题库ID] 共享给他人（仅创建者）")
        lines.append("使用 /取消共享 [用户QQ号] [自定义题库ID] 取消共享（仅创建者）")
        lines.append("使用 /题库信息 [自定义题库ID] 查看题库详情")

        await event.send(event.plain_result("\n".join(lines)))

    @filter.command("delbank", alias={"删除题库"})
    async def delbank(
        self,
        event: AstrMessageEvent,
        bank_id_arg: str = ""
    ):
        """删除自定义题库"""
        user_id = str(event.get_sender_id())
        umo = event.unified_msg_origin
        
        if not bank_id_arg:
            await event.send(event.plain_result("用法：/删除题库 [自定义题库ID]"))
            return
        
        try:
            bank_id = int(bank_id_arg)
        except ValueError:
            await event.send(event.plain_result("题库ID必须是数字。"))
            return

        bank_data = get_bank(user_id, bank_id)
        if not bank_data:
            await event.send(event.plain_result(f"不存在题库 {bank_id}，或你没有权限操作。"))
            return
        
        # 检查别名数量
        alias_data = export_custom_aliases(user_id, bank_id)
        alias_count = sum(len(aliases) for aliases in alias_data.values())
        
        if alias_count > 0:
            await event.send(event.plain_result(
                f"⚠️ 删除题库 {bank_id}“{bank_data['meta']['name']}”将同时删除该题库的所有别名（共 {alias_count} 个）。\n\n"
                f"输入 1：确认删除\n"
                f"输入 2：取消\n\n"
                f"请输入 1 或 2："
            ))
            # 设置等待状态
            set_upload_state(umo, {
                "step": "awaiting_del_confirm",
                "bank_id": bank_id
            })
            return
        
        # 无别名，直接删除
        if delete_bank(user_id, bank_id):
            await event.send(event.plain_result(f"✅ 题库 {bank_id} 已删除。"))
        else:
            await event.send(event.plain_result("删除失败。"))

    @filter.command("bankrename", alias={"改名", "修改题库名字"})
    async def bankrename(
        self,
        event: AstrMessageEvent,
        bank_id_arg: str = "",
        new_name: str = ""
    ):
        """修改自定义题库名称"""
        user_id = str(event.get_sender_id())
        
        if not bank_id_arg or not new_name:
            await event.send(event.plain_result("用法：/改名 [自定义题库ID] [新名称]"))
            return
        
        try:
            bank_id = int(bank_id_arg)
        except ValueError:
            await event.send(event.plain_result("题库ID必须是数字。"))
            return

        new_name = new_name.strip()
        if not new_name:
            await event.send(event.plain_result("新名称不能为空。"))
            return

        success, err = rename_bank(user_id, bank_id, new_name)
        if success:
            await event.send(event.plain_result(f"✅ 题库 {bank_id} 已重命名为“{new_name}”。"))
        else:
            await event.send(event.plain_result(f"❌ 重命名失败：{err if err else '未知错误，请检查题库ID或权限。'}"))

    @filter.command("bankinfo", alias={"题库信息"})
    async def bankinfo(
        self,
        event: AstrMessageEvent,
        bank_id_arg: str = ""
    ):
        """查看自定义题库详情（所有人可见）"""
        if not bank_id_arg:
            await event.send(event.plain_result("用法：/题库信息 [自定义题库ID]"))
            return

        try:
            bank_id = int(bank_id_arg)
        except ValueError:
            await event.send(event.plain_result("题库ID必须是数字。"))
            return

        user_id = str(event.get_sender_id())

        # ===== 从全局索引查题库 =====
        from .core.custom_bank_manager import _get_global_index
        index = _get_global_index()
        
        bank_entry = None
        for b in index["banks"]:
            if b["id"] == bank_id:
                bank_entry = b
                break
        
        if not bank_entry:
            await event.send(event.plain_result(f"题库 {bank_id} 不存在。"))
            return

        # ===== 读取 meta 和 songs =====
        uploader = bank_entry["uploader"]
        bank_dir = CUSTOM_BANK_DIR / uploader / str(bank_id)
        if not bank_dir.exists():
            await event.send(event.plain_result(f"题库 {bank_id} 数据丢失，请联系管理员。"))
            return

        meta_file = bank_dir / "meta.json"
        songs_file = bank_dir / "songs.json"
        if not meta_file.exists() or not songs_file.exists():
            await event.send(event.plain_result(f"题库 {bank_id} 数据损坏。"))
            return

        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        with open(songs_file, "r", encoding="utf-8") as f:
            songs = json.load(f)

        # ===== 判断当前用户与题库的关系 =====
        if bank_entry["uploader"] == user_id:
            role = "创建者"
        elif user_id in bank_entry.get("shared_with", []):
            role = "共享者"
        else:
            role = "无权限（仅查看）"

        upload_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(bank_entry["upload_time"]))

        # ===== 构造输出 =====
        lines = [
            f"📖 题库 {bank_id}：{bank_entry['name']}",
            "",
            f"上传者：{bank_entry['uploader']}",
            f"角色：{role}",
            f"上传时间：{upload_time}",
            f"歌曲数量：{bank_entry['song_count']} 首"
        ]

        # 共享列表
        shared_with = bank_entry.get("shared_with", [])
        if shared_with:
            lines.append("")
            lines.append(f"共享给：{', '.join(shared_with)}")
        else:
            lines.append("")
            lines.append("未共享给任何人")

        # 权限提示（仅对非创建者显示）
        if role != "创建者":
            lines.append("")
            if role == "共享者":
                lines.append("提示：你是共享者，可修改别名，不可修改题库内容或删除题库。")
            else:
                lines.append("提示：你仅可查看此题库，不可修改。")

        await event.send(event.plain_result("\n".join(lines)))
        
    # ---------------------- 题库共享 ----------------------
    @filter.command("共享题库")
    async def share_bank_cmd(
        self,
        event: AstrMessageEvent,
        target_user_id: str = "",
        bank_id_arg: str = ""
    ):
        """共享自定义题库给指定用户"""
        if not target_user_id or not bank_id_arg:
            await event.send(event.plain_result("用法：/共享题库 [用户QQ号] [自定义题库ID]"))
            return

        try:
            bank_id = int(bank_id_arg)
        except ValueError:
            await event.send(event.plain_result("题库ID必须是数字。"))
            return

        user_id = str(event.get_sender_id())
        success, msg = share_bank(user_id, bank_id, target_user_id)
        await event.send(event.plain_result(msg))

    @filter.command("取消共享")
    async def unshare_bank_cmd(
        self,
        event: AstrMessageEvent,
        target_user_id: str = "",
        bank_id_arg: str = ""
    ):
        """取消共享自定义题库"""
        if not target_user_id or not bank_id_arg:
            await event.send(event.plain_result("用法：/取消共享 [用户QQ号] [自定义题库ID]"))
            return

        try:
            bank_id = int(bank_id_arg)
        except ValueError:
            await event.send(event.plain_result("题库ID必须是数字。"))
            return

        user_id = str(event.get_sender_id())
        success, msg = unshare_bank(user_id, bank_id, target_user_id)
        await event.send(event.plain_result(msg))

    @filter.command("共享列表")
    async def shared_list_cmd(
        self,
        event: AstrMessageEvent,
        bank_id_arg: str = ""
    ):
        """查看题库共享给了谁"""
        if not bank_id_arg:
            await event.send(event.plain_result("用法：/共享列表 [自定义题库ID]"))
            return

        try:
            bank_id = int(bank_id_arg)
        except ValueError:
            await event.send(event.plain_result("题库ID必须是数字。"))
            return

        user_id = str(event.get_sender_id())
        success, result = get_shared_with(user_id, bank_id)

        if not success:
            await event.send(event.plain_result(result))
            return

        if not result:
            await event.send(event.plain_result(f"题库 {bank_id} 未共享给任何人。"))
            return

        text = f"题库 #{bank_id} 已共享给以下用户：\n\n"
        for uid in result:
            text += f"  {uid}\n"
        await event.send(event.plain_result(text))
        
    @filter.command("查看排行榜")
    async def view_leaderboard(
        self,
        event: AstrMessageEvent,
        preset_id_arg: str = ""
    ):
        """查看预设排行榜"""
        if not preset_id_arg:
            await event.send(event.plain_result("用法：/查看排行榜 [预设编号]"))
            return
        
        try:
            preset_id = int(preset_id_arg.strip())
        except ValueError:
            await event.send(event.plain_result("预设编号必须是数字。"))
            return
        
        from .core.preset_manager import get_preset, get_preset_leaderboard
        
        preset = get_preset(preset_id)
        if preset is None:
            await event.send(event.plain_result(f"不存在预设 #{preset_id}。"))
            return
        
        leaderboard = get_preset_leaderboard(preset_id)
        if not leaderboard:
            await event.send(event.plain_result(f"预设 #{preset_id} 暂无排行榜记录。"))
            return
        
        # 汇总所有群的所有用户得分
        all_entries = []
        for group_id, users in leaderboard.items():
            for user_id, score in users.items():
                if score > 0:  # 只显示有效得分
                    name = get_latest_name(user_id) or data.get("name", user_id)
                    all_entries.append((user_id, score, group_id))
        
        if not all_entries:
            await event.send(event.plain_result(f"预设 #{preset_id} 暂无有效排行榜记录。"))
            return
        
        # 按得分降序排列
        all_entries.sort(key=lambda x: x[1], reverse=True)
        
        lines = [f"🏆 排行榜 #{preset_id}："]
        for idx, (user_id, score, group_id) in enumerate(all_entries, 1):
            lines.append(f"#{idx}  {user_id}  {score}")
        
        await event.send(event.plain_result("\n".join(lines)))

    # ---------------------- 题库列表（显示个人禁用状态） ----------------------
    @filter.command("题库")
    async def db(self, event: AstrMessageEvent, args: str = ""):
        if args.strip():
            return
        bank_manager.auto_reload()

        user_id = event.get_sender_id()
        disabled_banks = get_disabled_banks(user_id)

        text = f"{user_id} 的题库状态：\n\n"

        # ===== 内置题库 =====
        text += "内置题库：\n"
        for name in bank_manager.get_bank_names():
            count = len([s for s in bank_manager.get_bank(name) if s.get("is_standard", False)])
            status = "❌ 已禁用" if name in disabled_banks else "✅ 已启用"
            text += f"  {name}: {count}首 {status}\n"

        # ===== 自定义题库 =====
        custom_banks = get_banks_list(user_id)
        if custom_banks:
            text += "\n自定义题库：\n"
            disabled_custom = get_disabled_custom_banks(user_id)
            for bank in custom_banks:
                status = "❌ 已禁用" if bank["id"] in disabled_custom else "✅ 已启用"
                text += f"  {bank['id']} {bank['name']}: {bank['song_count']}首 {status}\n"
            text += "\n使用 /mybanks 管理你的自定义题库"
        else:
            text += "\n（暂无自定义题库，使用 /uploadbank 上传）"

        total = len([s for s in bank_manager.get_all_songs() if s.get("is_standard", False)])
        # 加上自定义题库的歌曲数
        custom_songs = get_custom_songs(user_id)
        total += len(custom_songs)
        text += f"\n\n可用词库总计: {total}首"
        text += "\n\n使用 /禁用 [题库名] 或 /启用 [题库名] 切换内置题库和自定义题库状态"

        await event.send(event.plain_result(text))

    # ---------------------- 禁用题库 ----------------------
    @filter.command("禁用")
    async def cmd_disable(self, event: AstrMessageEvent):
        args = extract_args(event)
        if not args:
            await event.send(event.plain_result("用法：/禁用 [题库名] 或 /禁用 [自定义题库ID]"))
            return

        user_id = event.get_sender_id()
        arg = args.strip()

        # ===== 判断是否为自定义题库 =====
        if arg.isdigit():
            bank_id = int(arg)
            bank_data = get_bank(user_id, bank_id)
            if not bank_data:
                await event.send(event.plain_result(f"不存在自定义题库 {bank_id}，或你没有权限操作。"))
                return
            if disable_custom_bank(user_id, bank_id):
                await event.send(event.plain_result(f"已禁用自定义题库：{bank_data['meta']['name']}（{bank_id}）"))
            else:
                await event.send(event.plain_result(f"自定义题库 {bank_id} 已经是禁用状态。"))
            return

        # ===== 内置题库 =====
        bank_name = arg.lower()
        if bank_name not in bank_manager.get_bank_names():
            await event.send(event.plain_result(f"不存在题库：{bank_name}"))
            return
        if disable_bank(user_id, bank_name):
            await event.send(event.plain_result(f"已禁用题库：{bank_name}"))
        else:
            await event.send(event.plain_result(f"题库 {bank_name} 已经是禁用状态。"))
            
    # ---------------------- 启用题库 ----------------------
    @filter.command("启用")
    async def cmd_enable(self, event: AstrMessageEvent):
        args = extract_args(event)
        if not args:
            await event.send(event.plain_result("用法：/启用 [题库名] 或 /启用 [自定义题库ID]"))
            return

        user_id = event.get_sender_id()
        arg = args.strip()

        # ===== 判断是否为自定义题库 =====
        if arg.isdigit():
            bank_id = int(arg)
            bank_data = get_bank(user_id, bank_id)
            if not bank_data:
                await event.send(event.plain_result(f"不存在自定义题库 {bank_id}，或你没有权限操作。"))
                return
            if enable_custom_bank(user_id, bank_id):
                await event.send(event.plain_result(f"已启用自定义题库：{bank_data['meta']['name']}（{bank_id}）"))
            else:
                await event.send(event.plain_result(f"自定义题库 {bank_id} 已经是启用状态。"))
            return

        # ===== 内置题库 =====
        bank_name = arg.lower()
        if bank_name not in bank_manager.get_bank_names():
            await event.send(event.plain_result(f"不存在题库：{bank_name}"))
            return
        if enable_bank(user_id, bank_name):
            await event.send(event.plain_result(f"已启用题库：{bank_name}"))
        else:
            await event.send(event.plain_result(f"题库 {bank_name} 已经是启用状态。"))
            
    # ---------------------- 全部禁用 / 全部启用 ----------------------
    @filter.command("全部禁用")
    async def cmd_disable_all(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()

        # 禁用所有内置题库
        bank_names = bank_manager.get_bank_names()
        for bank_name in bank_names:
            disable_bank(user_id, bank_name)

        # 禁用所有自定义题库
        custom_banks = get_banks_list(user_id)
        for bank in custom_banks:
            disable_custom_bank(user_id, bank["id"])

        await event.send(event.plain_result("已禁用所有题库（包括自定义题库）。"))

    @filter.command("全部启用")
    async def cmd_enable_all(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()

        # 启用所有内置题库
        bank_names = bank_manager.get_bank_names()
        for bank_name in bank_names:
            enable_bank(user_id, bank_name)

        # 启用所有自定义题库
        custom_banks = get_banks_list(user_id)
        for bank in custom_banks:
            enable_custom_bank(user_id, bank["id"])

        await event.send(event.plain_result("已启用所有题库（包括自定义题库）。"))

    # ---------------------- 猜题 ----------------------
    @filter.command("猜", alias={"guess"})
    async def guess(self, event: AstrMessageEvent):
        event.call_llm = False
        event.stop_event()

        group_id, st = get_game_state(event, gm)
        if not st:
            await event.send(event.plain_result("当前没有进行中的开字母游戏。"))
            return

        # ===== 每日挑战超时检测 =====
        if st.get("daily_expire_at") and time.time() > st.get("daily_expire_at"):
            for q in st["questions"]:
                if q.get("type") != "decor":
                    q["mask"] = q["entry"]["title"]
            await send_question_board(event, st, "每日挑战已超时，游戏已结束，全部答案如下：")
            gm.end_game(group_id)
            return

        guess_text = extract_args(event)
        if not guess_text:
            await event.send(event.plain_result("用法：/猜 [曲名] 或 /guess [曲名]"))
            return

        _, reply = await guess_handler.handle_guess(event, st, guess_text)
        if gm.get_first_open_time(group_id) is None:
            gm.set_first_open_time(group_id, time.time())
        await event.send(event.plain_result(reply))

    # ---------------------- 查询歌曲（仅查询已启用题库） ----------------------
    @filter.command("查询", alias={"search"})
    async def search_song(self, event: AstrMessageEvent):
        event.call_llm = False
        event.stop_event()
        bank_manager.auto_reload()

        # ===== 统一使用 get_game_state 检查游戏状态 =====
        group_id, st = get_game_state(event, gm)
        if st:
            await event.send(event.plain_result("当前已有进行中的开字母游戏，查询功能已禁用。"))
            return

        # 获取原始消息文本（包含换行）
        raw_text = event.message_str.strip()
        
        # ===== 判断是否为批量查询 =====
        lines = raw_text.split("\n")
        # 如果第一行是 /查询 或 /search，去掉它
        first_line = lines[0].strip().lower()
        if first_line in ["/查询", "/search", "查询", "search"]:
            lines = lines[1:]
        
        # 检查是否存在序号开头的行（判断是否为批量查询）
        has_indexed_lines = False
        for line in lines:
            line = line.strip()
            if not line:
                continue
            import re
            if re.match(r'^\d+[.、．。)\]）]\s*', line):
                has_indexed_lines = True
                break
        
        if has_indexed_lines and len(lines) > 1:
            # ===== 批量查询模式 =====
            await self._batch_search(event, lines)
            return
        
        # ===== 单条查询模式 =====
        # 去掉命令前缀（/查询 或 /search 等）
        parts = raw_text.split(maxsplit=1)
        full_text = parts[1].strip() if len(parts) > 1 else ""
        
        # 解析 guessed 行
        lines = full_text.splitlines()
        guessed_letters = set()
        query_text = full_text
        if lines:
            first_line = lines[0].strip()
            guessed_match = re.match(r'^guessed\s*[:：]\s*(.*)$', first_line, re.IGNORECASE)
            if guessed_match:
                guessed_part = guessed_match.group(1).strip()
                guessed_letters = set(guessed_part)
                if len(lines) > 1:
                    query_text = "\n".join(lines[1:]).strip()
                else:
                    query_text = ""
        
        if not query_text:
            await event.send(event.plain_result("请输入查询模式，例如：\n/查询 4-6-4  或\n/查询 ***** ****  或\n/查询\n1.***** *****\n2.9-4\n3.*e* R******"))
            return

        # ===== 获取已启用的所有歌曲（在这里定义 all_songs） =====
        user_id = event.get_sender_id()
        disabled_banks = get_disabled_banks(user_id)
        all_songs = []
        for bank_name in bank_manager.get_bank_names():
            if bank_name in disabled_banks:
                continue
            all_songs.extend(bank_manager.get_bank(bank_name))
        custom_banks = get_banks_list(user_id)
        disabled_custom = get_disabled_custom_banks(user_id)
        for bank in custom_banks:
            if bank["id"] in disabled_custom:
                continue
            bank_data = get_bank(user_id, bank["id"])
            if bank_data:
                all_songs.extend(bank_data["songs"])
        
        # ===== 获取用户查询模式 =====
        from .core.user_settings import get_query_mode
        query_mode = get_query_mode(user_id)

        # 提取查询内容中的非 * 非空格字符（用于排除）
        extracted = {c for c in query_text if c != '*' and c != ' '}
        excluded = guessed_letters.union(extracted)

        mode, value = parse_query(query_text)
        if mode == "format":
            matches = search_format_code(all_songs, value)
        elif mode == "mask":
            matches = search_mask(all_songs, value, excluded_letters=excluded, mode=query_mode)
        else:
            await event.send(event.plain_result("查询格式错误，请使用：\n/查询 4-6-4\n/查询 ***** ****\n/查询 a*** ****"))
            return

        if not matches:
            await event.send(event.plain_result("未找到匹配"))
            return

        seen = set()
        unique = []
        for m in matches:
            if m["title"] not in seen:
                seen.add(m["title"])
                unique.append(m)

        text = "\n".join(f"{i+1}. {m['title']}" for i, m in enumerate(unique))
        mode_names = ["默认模式", "无视空格模式", "空格视作*模式", "无视已开字母模式"]
        text += f"\n（当前模式：{mode_names[query_mode]}，使用 /切换查询模式 可切换）"
        await event.send(event.plain_result(text))

    async def _batch_search(self, event, lines):
        """批量查询：每行一个序号+查询内容"""
        user_id = event.get_sender_id()
        
        # 获取已启用的所有歌曲
        disabled_banks = get_disabled_banks(user_id)
        all_songs = []
        for bank_name in bank_manager.get_bank_names():
            if bank_name in disabled_banks:
                continue
            all_songs.extend(bank_manager.get_bank(bank_name))
        custom_banks = get_banks_list(user_id)
        disabled_custom = get_disabled_custom_banks(user_id)
        for bank in custom_banks:
            if bank["id"] in disabled_custom:
                continue
            bank_data = get_bank(user_id, bank["id"])
            if bank_data:
                all_songs.extend(bank_data["songs"])

        # ===== 解析 guessed 行 =====
        import re
        guessed_letters = set()
        query_lines = lines[:]  # 复制
        if query_lines:
            first_line = query_lines[0].strip()
            guessed_match = re.match(r'^guessed\s*[:：]\s*(.*)$', first_line, re.IGNORECASE)
            if guessed_match:
                guessed_part = guessed_match.group(1).strip()
                guessed_letters = set(guessed_part)
                query_lines = query_lines[1:]  # 移除第一行

        # 跨行提取所有掩码中的非 * 非空格字符（只处理包含 * 的行）
        extracted = set()
        for line in query_lines:
            line = line.strip()
            if not line:
                continue
            match = re.match(r'^(\d+)[.、．。)\]）]\s*(.*)$', line)
            if match:
                mask = match.group(2).strip()
                # 如果掩码中不包含 *，说明这题已经全部揭开，跳过
                if '*' not in mask:
                    continue
                for ch in mask:
                    if ch != '*' and ch != ' ':
                        extracted.add(ch)
        excluded = guessed_letters.union(extracted)
        
        # ===== 获取用户查询模式 =====
        from .core.user_settings import get_query_mode
        query_mode = get_query_mode(user_id)

        # 解析每一行
        results = []  # 每个元素是 (序号, 匹配结果列表)
        for line in query_lines:
            line = line.strip()
            if not line:
                continue
            match = re.match(r'^(\d+)[.、．。)\]）]\s*(.*)$', line)
            if not match:
                continue
            idx = int(match.group(1))
            query = match.group(2).strip()
            if not query:
                results.append((idx, []))
                continue

            mode, value = parse_query(query)
            matches = []
            
            if mode == "format":
                matches = search_format_code(all_songs, value)
            elif mode == "mask":
                matches = search_mask(all_songs, value, excluded_letters=excluded, mode=query_mode)
            else:
                # 未识别为格式码或掩码，当作普通文本搜索（曲名/别名）
                target_norm = normalize_search(query)
                if not target_norm:  # 如果查询为空或纯空格，跳过
                    results.append((idx, []))
                    continue
                for song in all_songs:
                    title_norm = normalize_search(song["title"])
                    if target_norm in title_norm:
                        matches.append(song)
                    else:
                        aliases = get_aliases(song.get("bank", ""), song["title"])
                        for alias in aliases:
                            if target_norm in normalize_search(alias):
                                matches.append(song)
                                break
            
            # 去重
            seen = set()
            unique = []
            for m in matches:
                if m["title"] not in seen:
                    seen.add(m["title"])
                    unique.append(m)
            results.append((idx, unique))
        
        # ===== 构造输出 =====
        output_lines = []
        for idx, matches in results:
            output_lines.append(f"{idx}. ")
            if not matches:
                output_lines.append("无匹配")
            else:
                for m in matches:
                    output_lines.append(m["title"])
        
        # 去掉最后多余的空行
        while output_lines and output_lines[-1] == "":
            output_lines.pop()
        
        if not output_lines:
            await event.send(event.plain_result("未找到匹配"))
            return
        
        mode_names = ["默认模式", "无视空格模式", "空格视作*模式", "无视已开字母模式"]
        output_lines.append(f"（当前模式：{mode_names[query_mode]}，使用 /切换查询模式 可切换）")
        
        # 发送结果
        await event.send(event.plain_result("\n".join(output_lines)))
        
    @filter.command("切换查询模式")
    async def switch_query_mode(self, event: AstrMessageEvent, mode_arg: str = ""):
        """切换查询模式：0=默认，1=无视空格，2=空格=*，3=无视已开字母"""
        user_id = str(event.get_sender_id())
        
        if not mode_arg:
            current_mode = get_query_mode(user_id)
            mode_names = ["默认模式（严格匹配，*排除已开字母）", "无视空格模式", "空格视作*模式", "无视已开字母模式（*匹配所有字符）"]
            await event.send(event.plain_result(
                f"当前查询模式：{mode_names[current_mode]}（{current_mode}）\n\n"
                "用法：/切换查询模式 [0/1/2/3]\n"
                "0：默认模式：严格逐字符匹配，*排除已开字母\n"
                "1：无视空格模式：忽略所有空格\n"
                "2：空格视作*模式：*可以匹配空格\n"
                "3：无视已开字母模式：*匹配可以所有字符，不排除已开字母"
            ))
            return
        
        try:
            mode = int(mode_arg.strip())
        except ValueError:
            await event.send(event.plain_result("请输入 0、1、2 或 3。"))
            return
        
        if set_query_mode(user_id, mode):
            mode_names = ["默认模式（严格匹配）", "无视空格模式", "空格视作*模式", "无视已开字母模式"]
            await event.send(event.plain_result(f"✅ 已切换为：{mode_names[mode]}（{mode}）"))
        else:
            await event.send(event.plain_result("❌ 无效的模式，请输入 0、1、2 或 3。"))

    # ---------------------- 查曲（不受禁用影响） ----------------------
    @filter.command("查曲", alias={"song"})
    async def find_song(self, event: AstrMessageEvent):
        event.call_llm = False
        event.stop_event()
        bank_manager.auto_reload()

        target = extract_args(event)
        if not target:
            await event.send(event.plain_result("用法：/查曲 [曲名或别名]"))
            return

        user_id = event.get_sender_id()
        target_norm = normalize_search(target)
        exact_matches = []
        fuzzy_matches = []
        seen_exact = set()
        seen_fuzzy = set()

        # ===== 内置题库 =====
        for song in bank_manager.get_all_songs():
            if not song.get("is_standard", False):
                continue
            title_norm = normalize_search(song["title"])
            aliases_norm = [normalize_search(x) for x in get_aliases(song["bank"], song["title"])]

            if target_norm == title_norm or target_norm in aliases_norm:
                if song["title"] not in seen_exact:
                    exact_matches.append(song)
                    seen_exact.add(song["title"])
                continue

            if target_norm in title_norm:
                if song["title"] not in seen_fuzzy:
                    fuzzy_matches.append(song)
                    seen_fuzzy.add(song["title"])
                continue
            for alias in aliases_norm:
                if target_norm in alias:
                    if song["title"] not in seen_fuzzy:
                        fuzzy_matches.append(song)
                        seen_fuzzy.add(song["title"])
                    break

        # ===== 自定义题库 =====
        custom_songs = get_custom_songs(user_id)
        for song in custom_songs:
            title_norm = normalize_search(song["title"])
            # 获取该曲目在所有自定义题库中的别名
            from .core.custom_bank_manager import get_all_custom_aliases_for_song
            custom_aliases = get_all_custom_aliases_for_song(user_id, song["title"])
            aliases_norm = [normalize_search(x) for x in custom_aliases]

            if target_norm == title_norm or target_norm in aliases_norm:
                if song["title"] not in seen_exact:
                    exact_matches.append(song)
                    seen_exact.add(song["title"])
                continue

            if target_norm in title_norm:
                if song["title"] not in seen_fuzzy:
                    fuzzy_matches.append(song)
                    seen_fuzzy.add(song["title"])
                continue
            for alias in aliases_norm:
                if target_norm in alias:
                    if song["title"] not in seen_fuzzy:
                        fuzzy_matches.append(song)
                        seen_fuzzy.add(song["title"])
                    break

        matches = exact_matches if exact_matches else fuzzy_matches
        if not matches:
            await event.send(event.plain_result("未找到该曲目"))
            return

        key = event.unified_msg_origin
        if len(matches) == 1:
            set_pending_alias(key, {"song": matches[0], "expire": time.time() + PENDING_ALIAS_TIMEOUT})
            await show_song_info(event, matches[0], user_id) 
            return

        set_pending_query(key, {"songs": matches, "expire": time.time() + PENDING_QUERY_TIMEOUT})
        lines = ["找到多个结果，请在 60 秒内输入序号："]
        for i, song in enumerate(matches, 1):
            lines.append(f"{i}. {song['title']}")
        await event.send(event.plain_result("\n".join(lines)))

    # ---------------------- 加别名 ----------------------
    @filter.command("加别名", alias={"addalias"})
    async def add_alias(self, event: AstrMessageEvent):
        new_alias = extract_args(event)
        if not new_alias:
            await event.send(event.plain_result("请先使用 /查曲 选择歌曲\n然后输入：/加别名 [别名]"))
            return

        target_song = self.get_pending_song(event)
        if not target_song:
            await event.send(event.plain_result("请先使用 /查曲 选择歌曲"))
            return

        user_id = event.get_sender_id()
        title = target_song["title"]
        
        # 检查该曲目是否存在于自定义题库中
        custom_bank_id = get_custom_bank_id_by_song(user_id, title)
        
        # 检查该曲目是否存在于内置题库中
        in_default = False
        for song in bank_manager.get_all_songs():
            if song["title"] == title:
                in_default = True
                break
        
        # 情况1：仅存在于自定义题库
        if custom_bank_id and not in_default:
            if add_custom_alias(user_id, custom_bank_id, title, new_alias):
                await event.send(event.plain_result(f"已添加别名：{title} -> {new_alias}"))
            else:
                await event.send(event.plain_result("该别名已存在。"))
            return
        
        # 情况2：仅存在于内置题库
        if in_default and not custom_bank_id:
            # 走现有审核流程
            if is_admin(event):
                aliases = get_aliases(target_song["bank"], target_song["title"])
                if new_alias.lower() in [x.lower() for x in aliases]:
                    await event.send(event.plain_result("该别名已存在。"))
                    return
                add_alias_to_file(target_song["bank"], target_song["title"], new_alias)
                await event.send(event.plain_result(f"管理员添加别名：{target_song['title']} -> {new_alias}"))
                return
            else:
                if new_alias.lower() == target_song["title"].lower():
                    await event.send(event.plain_result("曲名本身不能作为别名。"))
                    return
                for alias in get_aliases(target_song["bank"], target_song["title"]):
                    if alias.lower() == new_alias.lower():
                        await event.send(event.plain_result("该别名已经存在。"))
                        return
                for item in approval_mgr.list_all():
                    if item["title"] == target_song["title"] and item["alias"].lower() == new_alias.lower():
                        await event.send(event.plain_result(f"该别名已经提交审核（编号 {item['id']}）"))
                        return
                aid = approval_mgr.add(target_song["bank"], target_song["title"], new_alias, event.get_sender_id())
                await event.send(event.plain_result(f"已提交审核 | 编号 {aid} | 歌名 {target_song['title']} | 别名 {new_alias}"))
            return
        
        # 情况3：同时存在于内置和自定义
        if in_default and custom_bank_id:
            key = event.unified_msg_origin
            set_pending_query(key, {
                "action": "add_alias_choice",
                "title": title,
                "alias": new_alias,
                "custom_bank_id": custom_bank_id,
                "expire": time.time() + 300
            })
            await event.send(event.plain_result(
                f"该曲目同时存在于内置题库和你的自定义题库中。\n\n"
                f"请选择别名添加位置：\n"
                f"1. 仅添加到自己的自定义题库\n"
                f"2. 仅添加到内置题库\n"
                f"3. 同时添加到自定义题库和内置题库\n\n"
                f"请输入 1、2 或 3："
            ))
            return
        
    @filter.command("删别名", alias={"delalias"})
    async def delete_alias(self, event: AstrMessageEvent):
        """删除别名（支持内置题库和自定义题库）"""
        new_alias = extract_args(event)
        if not new_alias:
            await event.send(event.plain_result("请先使用 /查曲 选择歌曲\n然后输入：/删别名 [别名]"))
            return

        target_song = self.get_pending_song(event)
        if not target_song:
            await event.send(event.plain_result("请先使用 /查曲 选择歌曲"))
            return

        user_id = event.get_sender_id()
        title = target_song["title"]
        alias_to_delete = new_alias
        
        # 检查该曲目是否存在于自定义题库中
        custom_bank_id = get_custom_bank_id_by_song(user_id, title)
        
        # 检查该曲目是否存在于内置题库中，并获取内置bank名称
        in_default = False
        default_bank = None
        for song in bank_manager.get_all_songs():
            if song["title"] == title:
                in_default = True
                default_bank = song["bank"]
                break
        
        # 获取自定义别名列表（如果存在）
        custom_aliases = []
        if custom_bank_id:
            custom_aliases = get_custom_aliases(user_id, custom_bank_id, title)
        
        # 获取内置别名列表（如果存在）
        default_aliases = []
        if default_bank:
            default_aliases = get_aliases(default_bank, title)
        
        # 检查别名是否实际存在
        in_custom = alias_to_delete in custom_aliases
        in_default_alias = alias_to_delete.lower() in [x.lower() for x in default_aliases]
        
        if not in_custom and not in_default_alias:
            await event.send(event.plain_result(f"该歌曲不存在别名：{alias_to_delete}"))
            return
        
        # 情况1：仅存在于自定义题库
        if in_custom and not in_default_alias:
            if remove_custom_alias(user_id, custom_bank_id, title, alias_to_delete):
                await event.send(event.plain_result(f"已删除别名：{title} -> {alias_to_delete}"))
            else:
                await event.send(event.plain_result("删除失败，请重试。"))
            return
        
        # 情况2：仅存在于内置题库
        if in_default_alias and not in_custom:
            if not is_admin(event):
                await event.send(event.plain_result("你没有权限删除内置题库的别名（仅管理员可操作）。"))
                return
            remove_alias_from_file(default_bank, title, alias_to_delete)
            await event.send(event.plain_result(f"已删除别名：{title} -> {alias_to_delete}"))
            return
        
        # 情况3：同时存在于两个库 → 弹选择框
        key = event.unified_msg_origin
        if is_admin(event):
            set_pending_query(key, {
                "action": "delete_alias_choice",
                "title": title,
                "alias": alias_to_delete,
                "custom_bank_id": custom_bank_id,
                "default_bank": default_bank,
                "expire": time.time() + 300
            })
            await event.send(event.plain_result(
                f"该别名同时存在于内置题库和你的自定义题库中。\n\n"
                f"请选择别名删除位置：\n"
                f"1. 仅删除自己的自定义题库中的别名\n"
                f"2. 仅删除内置题库中的别名\n"
                f"3. 同时删除自定义题库和内置题库中的别名\n\n"
                f"请输入 1、2 或 3："
            ))
        else:
            set_pending_query(key, {
                "action": "delete_alias_choice",
                "title": title,
                "alias": alias_to_delete,
                "custom_bank_id": custom_bank_id,
                "default_bank": default_bank,
                "expire": time.time() + 300
            })
            await event.send(event.plain_result(
                f"该别名同时存在于内置题库和你的自定义题库中。\n\n"
                f"你只能删除自己自定义题库中的别名。\n"
                f"输入 1：仅删除自定义题库中的别名\n"
                f"输入 2：取消\n\n"
                f"请输入 1 或 2："
            ))
            return
    
    @filter.command("导入别名")
    async def import_aliases(self, event: AstrMessageEvent, args: str = ""):
        """导入别名（支持自定义题库和内置题库）"""
        if event.get_group_id():
            await event.send(event.plain_result("请私聊使用此命令。"))
            return

        parts = args.strip().split()
        if not parts:
            await event.send(event.plain_result("用法：/导入别名 [自定义题库ID] 或 /导入别名 [内置题库名]"))
            return

        user_id = str(event.get_sender_id())
        umo = event.unified_msg_origin
        arg = parts[0]

        # ===== 自定义题库 =====
        if arg.isdigit():  # 改为纯数字判断
            bank_id = int(arg)
            bank_data = get_bank(user_id, bank_id)
            if not bank_data:
                await event.send(event.plain_result(f"不存在自定义题库 {bank_id}，或你没有权限操作。"))
                return

            # 检查是否有现有别名，提示覆盖
            existing = export_custom_aliases(user_id, bank_id)
            if existing:
                alias_count = sum(len(aliases) for aliases in existing.values())
                await event.send(event.plain_result(
                    f"⚠️ 该题库已有别名数据（共 {alias_count} 个），导入将覆盖现有别名。\n\n"
                    f"输入 1：确认继续\n"
                    f"输入 2：取消\n\n"
                    f"请输入 1 或 2："
                ))
                set_upload_state(umo, {
                    "step": "awaiting_import_confirm",
                    "bank_id": bank_id,
                    "target_type": "custom"
                })
                return

            # 直接进入选择界面
            set_upload_state(umo, {
                "step": "awaiting_alias_method",
                "bank_id": bank_id,
                "target_type": "custom"
            })
            await event.send(event.plain_result(
                "请选择别名导入方式：\n"
                "1. 发送 Excel 文件（.xlsx）\n"
                "2. 发送纯文本（每行一个曲目，全角逗号分隔别名）\n\n"
                "请输入 1 或 2："
            ))
            return

        # ===== 内置题库 =====
        bank_name = arg.lower()
        if bank_name not in bank_manager.get_bank_names():
            await event.send(event.plain_result(f"不存在内置题库：{bank_name}"))
            return

        if not self.is_plugin_admin(event):
            await event.send(event.plain_result("你没有权限导入内置题库的别名，仅管理员可操作。"))
            return

        # 检查是否有现有别名
        from .core.alias_manager import get_alias_file
        alias_file = get_alias_file(bank_name)
        if alias_file.exists():
            with open(alias_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            alias_count = sum(len(aliases) for aliases in existing.values())
            await event.send(event.plain_result(
                f"⚠️ 该内置题库已有别名数据（共 {alias_count} 个），导入将覆盖现有别名。\n\n"
                f"输入 1：确认继续\n"
                f"输入 2：取消\n\n"
                f"请输入 1 或 2："
            ))
            set_upload_state(umo, {
                "step": "awaiting_import_confirm",
                "bank_name": bank_name,
                "target_type": "default"
            })
            return

        set_upload_state(umo, {
            "step": "awaiting_alias_method",
            "bank_name": bank_name,
            "target_type": "default"
        })
        await event.send(event.plain_result(
            "请选择别名导入方式：\n"
            "1. 发送 Excel 文件（.xlsx）\n"
            "2. 发送纯文本（每行一个曲目，全角逗号分隔别名）\n\n"
            "请输入 1 或 2："
        ))
    
    @filter.command("导出别名")
    async def export_aliases(self, event: AstrMessageEvent, args: str = ""):
        """导出别名（支持自定义题库和内置题库）"""
        parts = args.strip().split()
        if not parts:
            await event.send(event.plain_result("用法：/导出别名 [自定义题库ID] 或 /导出别名 [内置题库名]"))
            return

        user_id = str(event.get_sender_id())
        arg = parts[0]

        # ===== 自定义题库 =====
        if arg.isdigit():
            try:
                bank_id = int(arg)
            except ValueError:
                await event.send(event.plain_result("题库ID必须是数字。"))
                return

            bank_data = get_bank(user_id, bank_id)
            if not bank_data:
                await event.send(event.plain_result(f"不存在自定义题库 {bank_id}，或你没有权限操作。"))
                return

            alias_data = export_custom_aliases(user_id, bank_id)
            if not alias_data:
                await event.send(event.plain_result(f"自定义题库 {bank_id} 暂无别名数据。"))
                return

            # 生成 Excel
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = bank_data["meta"]["name"]
            ws.append(["曲名", "别名"])
            for title, aliases in alias_data.items():
                ws.append([title, "，".join(aliases)])
            
            temp_path = PLUGIN_TEMP_DIR / f"alias_export_{user_id}_{bank_id}_{int(time.time())}.xlsx"
            wb.save(temp_path)
            await event.send(MessageChain([Comp.File(file=str(temp_path), name=temp_path.name)]))
            temp_path.unlink(missing_ok=True)
            return

        # ===== 内置题库 =====
        bank_name = arg.lower()
        if bank_name not in bank_manager.get_bank_names():
            await event.send(event.plain_result(f"不存在内置题库：{bank_name}"))
            return

        # 读取内置题库的别名文件
        from .core.alias_manager import get_alias_file
        alias_file = get_alias_file(bank_name)
        if not alias_file.exists():
            await event.send(event.plain_result(f"内置题库 {bank_name} 暂无别名数据。"))
            return

        with open(alias_file, "r", encoding="utf-8") as f:
            alias_data = json.load(f)

        # 生成 Excel
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = bank_name
        ws.append(["曲名", "别名"])
        for title, aliases in alias_data.items():
            if aliases:
                ws.append([title, "，".join(aliases)])

        temp_path = PLUGIN_TEMP_DIR / f"alias_export_default_{bank_name}_{int(time.time())}.xlsx"
        wb.save(temp_path)
        await event.send(MessageChain([Comp.File(file=str(temp_path), name=temp_path.name)]))
        temp_path.unlink(missing_ok=True)

    # ---------------------- 通过别名 ----------------------
    @filter.command("通过", alias={"approve"})
    async def approve_alias(self, event: AstrMessageEvent):
        if not self.is_plugin_admin(event):
            await event.send(event.plain_result("权限不足，仅管理员可操作。"))
            return
        ids_text = extract_args(event)
        if not ids_text:
            await event.send(event.plain_result("用法：/通过 [编号] 或 /通过 1-3"))
            return

        try:
            if "-" in ids_text:
                start, end = ids_text.split("-", 1)
                start, end = int(start), int(end)
                if start > end:
                    start, end = end, start
                approve_ids = list(range(start, end + 1))
            else:
                approve_ids = [int(ids_text)]
        except:
            await event.send(event.plain_result("编号是数字！"))
            return

        success = 0
        for aid in approve_ids:
            item = approval_mgr.find_by_id(aid)
            if not item:
                continue
            add_alias_to_file(item["bank"], item["title"], item["alias"])
            approval_mgr.remove(item)
            success += 1

        await event.send(event.plain_result(f"已通过 {success} 条别名申请。"))

    # ---------------------- 全部通过 ----------------------
    @filter.command("全部通过")
    async def approve_all_alias(self, event: AstrMessageEvent):
        if not self.is_plugin_admin(event):
            await event.send(event.plain_result("权限不足，仅管理员可操作。"))
            return
        if approval_mgr.is_empty():
            await event.send(event.plain_result("当前没有待审核别名。"))
            return
        count = 0
        for item in approval_mgr.list_all()[:]:
            add_alias_to_file(item["bank"], item["title"], item["alias"])
            count += 1
        approval_mgr.clear()
        await event.send(event.plain_result(f"已通过全部待审核别名，共 {count} 条。"))

    # ---------------------- 拒绝别名 ----------------------
    @filter.command("拒绝", alias={"reject"})
    async def reject_alias(self, event: AstrMessageEvent):
        if not self.is_plugin_admin(event):
            await event.send(event.plain_result("权限不足，仅管理员可操作。"))
            return
        ids_text = extract_args(event)
        if not ids_text:
            await event.send(event.plain_result("用法：/拒绝 [编号] 或 /拒绝 1-3"))
            return

        try:
            if "-" in ids_text:
                start, end = ids_text.split("-", 1)
                start, end = int(start), int(end)
                if start > end:
                    start, end = end, start
                reject_ids = list(range(start, end + 1))
            else:
                reject_ids = [int(ids_text)]
        except:
            await event.send(event.plain_result("编号是数字！"))
            return

        success = 0
        for aid in reject_ids:
            item = approval_mgr.find_by_id(aid)
            if item:
                approval_mgr.remove(item)
                success += 1
        await event.send(event.plain_result(f"已拒绝 {success} 条别名申请。"))

    # ---------------------- 全部拒绝 ----------------------
    @filter.command("全部拒绝")
    async def reject_all_alias(self, event: AstrMessageEvent):
        if not self.is_plugin_admin(event):
            await event.send(event.plain_result("权限不足，仅管理员可操作。"))
            return
        if approval_mgr.is_empty():
            await event.send(event.plain_result("当前没有待审核别名。"))
            return
        count = approval_mgr.clear()
        await event.send(event.plain_result(f"已拒绝全部待审核别名，共 {count} 条。"))

    # ---------------------- 待审列表 ----------------------
    @filter.command("待审", alias={"pending"})
    async def list_pending_alias(self, event: AstrMessageEvent):
        if not self.is_plugin_admin(event):
            await event.send(event.plain_result("权限不足，仅管理员可操作。"))
            return
        if approval_mgr.is_empty():
            await event.send(event.plain_result("当前没有待审核别名。"))
            return
        lines = ["待审核别名列表："]
        for item in approval_mgr.list_all():
            lines.append(f"{item['id']}. {item['title']} -> {item['alias']} (提交者:{item['user']})")
        await event.send(event.plain_result("\n".join(lines)))
        
    @filter.command("比赛模式")
    async def competition_mode(self, event: AstrMessageEvent, args: str = ""):
        # 确定对话ID
        group_id = event.get_group_id()
        if not group_id:
            group_id = f"private_{event.get_sender_id()}"
        group_id = str(group_id)

        # 获取当前游戏状态
        st = gm.get_state(group_id)
        has_started = gm.get_first_open_time(group_id) is not None
        has_game = st is not None

        # 获取比赛模式设置
        state = get_competition_state(group_id)
        enabled = state.get("enabled", False)
        once = state.get("once", False)

        # 显示状态
        if not args.strip():
            status = "开启" if enabled else "关闭"
            once_status = "（已标记单次开启）" if once else ""
            game_status = "（当前有游戏，未开字母）" if has_game and not has_started else "（当前有游戏，已开字母）" if has_game and has_started else "（当前无游戏）"
            msg = f"当前比赛模式状态：{status} {once_status}\n"
            msg += f"{game_status}\n\n"
            msg += "1. 切换持续状态\n"
            msg += "2. 仅下一次或本次开字母开启\n"
            msg += "3. 退出比赛模式\n\n"
            msg += "用法：/比赛模式 [1/2/3]"
            await event.send(event.plain_result(msg))
            return

        choice = args.strip()

        # ========== 选项1：切换持续状态 ==========
        if choice == "1":
            # 如果已开字母，禁止操作
            if has_game and has_started:
                await event.send(event.plain_result("❌ 比赛模式已无法更改。"))
                return

            new_enabled = not enabled
            set_competition_state(group_id, enabled=new_enabled)
            if not new_enabled:
                set_competition_state(group_id, once=False)

            # 如果有游戏且未开字母，立即应用到当前游戏
            if has_game and not has_started:
                gm.set_competition_mode(group_id, new_enabled)
                action = "开启" if new_enabled else "关闭"
                await event.send(event.plain_result(f"✅ 比赛模式已{action}，将对当前开字母生效。"))
            else:
                status = "开启" if new_enabled else "关闭"
                await event.send(event.plain_result(f"✅ 比赛模式已{status}。"))

        # ========== 选项2：标记单次开启 ==========
        elif choice == "2":
            # 如果已开字母或已答题，禁止操作
            if has_game and has_started:
                await event.send(event.plain_result("❌ 比赛模式已无法更改。"))
                return

            set_competition_state(group_id, once=True)

            # 如果有游戏且未开字母，立即应用到当前游戏并消耗标记
            if has_game and not has_started:
                gm.set_competition_mode(group_id, True)
                consume_competition_once(group_id)  # 消耗标记
                await event.send(event.plain_result("✅ 比赛模式已开启，仅对当前开字母生效。"))
            else:
                await event.send(event.plain_result("✅ 下一次开字母将开启单次比赛模式。"))

        # ========== 选项3：退出所有状态 ==========
        elif choice == "3":
            # 如果已开字母，禁止操作
            if has_game and has_started:
                await event.send(event.plain_result("❌ 比赛模式已无法更改。"))
                return

            set_competition_state(group_id, enabled=False, once=False)

            # 如果有游戏且未开字母，立即关闭当前游戏的比赛模式
            if has_game and not has_started:
                gm.set_competition_mode(group_id, False)
                await event.send(event.plain_result("✅ 比赛模式已关闭，将对当前开字母生效。"))
            else:
                await event.send(event.plain_result("✅ 比赛模式已关闭。"))

        else:
            await event.send(event.plain_result("请输入正确数字。"))

    # ---------------------- 曲目待审（B站巡检产出） ----------------------
    def _write_songs_to_bank(self, game, titles, is_standard=True):
        import json as _json
        bank_dir = song_fetcher.BANK_DIR / game
        bank_dir.mkdir(parents=True, exist_ok=True)
        f = bank_dir / "songs.json"
        songs = []
        if f.exists():
            with open(f, "r", encoding="utf-8") as fp:
                songs = _json.load(fp)
        exist = set()
        for s in songs:
            t = s.get("title") if isinstance(s, dict) else s
            if t:
                exist.add(song_fetcher.norm_title(t))
        added = 0
        for t in titles:
            k = song_fetcher.norm_title(t)
            if not k or k in exist:
                continue
            songs.append({"title": t, "is_standard": is_standard})
            exist.add(k)
            added += 1
        with open(f, "w", encoding="utf-8") as fp:
            _json.dump(songs, fp, ensure_ascii=False, indent=2)
        return added

    @filter.command("曲目待审", alias={"songpending"})
    async def list_pending_songs(self, event: AstrMessageEvent):
        event.call_llm = False
        event.stop_event()
        if not self.is_plugin_admin(event):
            await event.send(event.plain_result("只有管理员能用这个指令。"))
            return
        data = song_fetcher.load_pending()
        pending = data.get("pending", [])
        if not pending:
            await event.send(event.plain_result("当前没有待审核曲目。"))
            return
        by_game = {}
        for x in pending:
            by_game.setdefault(x.get("game", "?"), []).append(x)
        lines = ["待审核曲目："]
        for game, items in by_game.items():
            lines.append("")
            lines.append(f"【{game}】")
            for label, flag in (("标准：", True), ("非标准：", False)):
                group = [
                    x for x in items
                    if bool(x.get("is_standard", True)) == flag
                ]
                if not group:
                    continue
                lines.append(label)
                for x in group:
                    lines.append(f'{x.get("id")}. {x.get("title")}')
        lines.append("")
        lines.append("处理：/通过曲目 [编号] 或 /通过曲目 1-3")
        await event.send(event.plain_result("\n".join(lines)))

    @filter.command("通过曲目", alias={"songapprove"})
    async def approve_pending_songs(self, event: AstrMessageEvent):
        event.call_llm = False
        event.stop_event()
        if not self.is_plugin_admin(event):
            await event.send(event.plain_result("这个只有管理员能用。"))
            return
        ids_text = extract_args(event).strip()
        if not ids_text:
            await event.send(event.plain_result("用法：/通过曲目 [编号] 或 /通过曲目 1-3"))
            return
        data = song_fetcher.load_pending()
        pending = data.get("pending", [])
        if not pending:
            await event.send(event.plain_result("当前没有待审核曲目。"))
            return
        try:
            if "-" in ids_text:
                a, b = ids_text.split("-", 1)
                a, b = int(a), int(b)
                if a > b:
                    a, b = b, a
                want = set(range(a, b + 1))
            else:
                want = {int(ids_text)}
        except Exception:
            await event.send(event.plain_result("编号是数字！"))
            return
        picked = [x for x in pending if x.get("id") in want]
        if not picked:
            await event.send(event.plain_result("未找到对应编号。"))
            return

        by_game = {}
        for x in picked:
            by_game.setdefault(x["game"], []).append(x)

        total = 0
        for game, items in by_game.items():
            std = [x["title"] for x in items if x.get("is_standard", True)]
            non = [x["title"] for x in items if not x.get("is_standard", True)]
            total += self._write_songs_to_bank(game, std, True)
            total += self._write_songs_to_bank(game, non, False)
            for t in std:
                try:
                    sync_aliases_for_title(t)
                except Exception:
                    pass

        done = {x["id"] for x in picked}
        data["pending"] = [x for x in pending if x.get("id") not in done]
        song_fetcher.save_pending(data)
        bank_manager.force_reload()
        await event.send(event.plain_result(f"通过 {len(picked)} 条，实际写入 {total} 条。"))

    @filter.command("拒绝曲目", alias={"songreject"})
    async def reject_pending_songs(self, event: AstrMessageEvent):
        event.call_llm = False
        event.stop_event()
        if not self.is_plugin_admin(event):
            await event.send(event.plain_result("只有管理员能用这个指令。"))
            return
        ids_text = extract_args(event).strip()
        if not ids_text:
            await event.send(event.plain_result("用法：/拒绝曲目 [编号] 或 /拒绝曲目 1-3"))
            return
        data = song_fetcher.load_pending()
        pending = data.get("pending", [])
        if not pending:
            await event.send(event.plain_result("当前没有待审核曲目。"))
            return
        try:
            if "-" in ids_text:
                a, b = ids_text.split("-", 1)
                a, b = int(a), int(b)
                if a > b:
                    a, b = b, a
                want = set(range(a, b + 1))
            else:
                want = {int(ids_text)}
        except Exception:
            await event.send(event.plain_result("编号是数字！"))
            return
        picked = [x for x in pending if x.get("id") in want]
        if not picked:
            await event.send(event.plain_result("没找到对应编号。"))
            return

        for x in picked:
            data["rejected"].append({
                "game": x.get("game"),
                "title": x.get("title"),
                "at": int(time.time()),
            })
        done = {x["id"] for x in picked}
        data["pending"] = [x for x in pending if x.get("id") not in done]
        song_fetcher.save_pending(data)
        await event.send(event.plain_result(f"已拒绝 {len(picked)} 条，以后不再提醒。"))

    @filter.command("全部通过曲目")
    async def approve_all_pending_songs(self, event: AstrMessageEvent):
        event.call_llm = False
        event.stop_event()
        if not self.is_plugin_admin(event):
            await event.send(event.plain_result("只有管理员能用这个指令。"))
            return
        data = song_fetcher.load_pending()
        pending = data.get("pending", [])
        if not pending:
            await event.send(event.plain_result("当前没有待审核曲目。"))
            return
        by_game = {}
        for x in pending:
            by_game.setdefault(x["game"], []).append(x)
        total = 0
        for game, items in by_game.items():
            std = [x["title"] for x in items if x.get("is_standard", True)]
            non = [x["title"] for x in items if not x.get("is_standard", True)]
            total += self._write_songs_to_bank(game, std, True)
            total += self._write_songs_to_bank(game, non, False)
            for t in std:
                try:
                    sync_aliases_for_title(t)
                except Exception:
                    pass
        data["pending"] = []
        song_fetcher.save_pending(data)
        bank_manager.force_reload()
        await event.send(event.plain_result(f"已通过全部待审核曲目，共 {len(pending)} 条，实际写入 {total} 条。"))

    @filter.command("全部拒绝曲目")
    async def reject_all_pending_songs(self, event: AstrMessageEvent):
        event.call_llm = False
        event.stop_event()
        if not self.is_plugin_admin(event):
            await event.send(event.plain_result("只有管理员能用这个指令。"))
            return
        data = song_fetcher.load_pending()
        pending = data.get("pending", [])
        if not pending:
            await event.send(event.plain_result("当前没有待审核曲目。"))
            return
        for x in pending:
            data["rejected"].append({
                "game": x.get("game"),
                "title": x.get("title"),
                "at": int(time.time()),
            })
        data["pending"] = []
        song_fetcher.save_pending(data)
        await event.send(event.plain_result(f"已拒绝全部待审核曲目，共 {len(pending)} 条。"))

    @filter.command("立即获取曲目", alias={"songfetch"})
    async def fetch_songs_now(self, event: AstrMessageEvent):
        event.call_llm = False
        event.stop_event()
        if not self.is_plugin_admin(event):
            await event.send(event.plain_result("只有管理员能用这个指令。"))
            return
        if getattr(self, "_song_fetching", False):
            await event.send(event.plain_result("上次抓取还在进行。"))
            return

        self._song_fetching = True
        await event.send(event.plain_result("开始抓取，可能需要一定时间……"))
        try:
            res = await asyncio.to_thread(song_fetcher.run_once, 1)
        except Exception as e:
            logger.error(f"[LetterGame] 手动抓取失败: {e}")
            await event.send(event.plain_result(f"抓取失败：{e}"))
            return
        finally:
            self._song_fetching = False

        if not res.get("ok"):
            await event.send(event.plain_result(f"抓取失败：{res.get('reason')}"))
            return

        added = res.get("added", 0)
        per = res.get("per_game", {}) or {}
        detail = "  ".join(f"{g} +{n}" for g, n in per.items() if n)
        if added:
            lines = [f"抓取完成，新增 {added} 条待审。"]
            if detail:
                lines.append(detail)
            lines.append("可以使用 /曲目待审 查看清单。")
        else:
            lines = ["抓取完成，这次没有新曲。"]
        await event.send(event.plain_result("\n".join(lines)))

    # ---------------------- 曲目巡检：每周五 21:00 ----------------------
    async def initialize(self):
        try:
            await super().initialize()
        except Exception:
            pass
        if not getattr(self, "_song_fetch_started", False):
            self._song_fetch_started = True
            self._song_fetch_task = asyncio.create_task(self._song_fetch_loop())
            logger.info("[LetterGame] 曲目巡检已启动（每周五 21:00）")

    async def terminate(self):
        task = getattr(self, "_song_fetch_task", None)
        if task:
            task.cancel()
        try:
            await super().terminate()
        except Exception:
            pass

    async def _song_fetch_loop(self):
        import datetime as _dt
        while True:
            now = _dt.datetime.now()
            days = (4 - now.weekday()) % 7
            target = (now + _dt.timedelta(days=days)).replace(
                hour=21, minute=0, second=0, microsecond=0
            )
            if target <= now:
                target = target + _dt.timedelta(days=7)
            wait = max((target - now).total_seconds(), 60)
            logger.info(f"[LetterGame] 下次曲目巡检: {target:%Y-%m-%d %H:%M}")
            try:
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                return
            try:
                res = song_fetcher.run_once(pages=1)
                logger.info(
                    f"[LetterGame] 曲目巡检完成 added={res.get('added')} "
                    f"per_game={res.get('per_game')}"
                )
            except Exception as e:
                logger.error(f"[LetterGame] 曲目巡检失败: {e}")

    # ---------------------- 辅助方法 ----------------------
    def get_pending_song(self, event):
        key = event.unified_msg_origin
        data = get_pending_alias(key)
        if not data or time.time() > data["expire"]:
            remove_pending_alias(key)
            return None
        return data["song"]