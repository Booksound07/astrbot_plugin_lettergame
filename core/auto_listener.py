import re
import time
import math
from astrbot.api import logger
from difflib import SequenceMatcher
from .matcher import match_answer
from .llm_matcher import llm_match
from .alias_manager import get_shared_aliases
from .helpers import send_question_board
from .scoring import (
    calculate_single_score,
    calculate_all_scores,
    get_time_multiplier,
    get_difficulty_multiplier,
    get_opened_letters_multiplier,
    get_question_opened_multiplier
)
from .utils import is_revealed
from .constants import COMMAND_SET, STRING_SIMILARITY_THRESHOLD

def calculate_similarity(text1: str, text2: str) -> float:
    """计算两个字符串的字符相似度，返回 0~100"""
    text1 = text1.strip().lower()
    text2 = text2.strip().lower()

    if not text1 or not text2:
        return 0.0

    return SequenceMatcher(
        None,
        text1,
        text2
    ).ratio() * 100

class AutoListener:
    def __init__(
        self,
        gm,
        bank_manager,
        context,
        llm_matcher_provider_id=""
    ):
        self.gm = gm
        self.bank_manager = bank_manager
        self.context = context
        self.llm_matcher_provider_id = llm_matcher_provider_id

    def extract_guess_content(self, text: str):
        """
        检测消息是否以序号开头，提取序号后面的内容
        支持格式：1. 1、 1． 1。 1.  1)  1） 等
        返回：(序号, 提取的内容) 或 (None, 原文本)
        """
        pattern = r'^(\d+)[.、．。)\]）]?\s*(.*)$'
        match = re.match(pattern, text.strip())
        if match:
            return int(match.group(1)), match.group(2).strip()
        return None, text.strip()

    def _find_question_by_index(self, st, idx):
        """根据序号查找题目（1-based）"""
        question_idx = idx - 1
        if question_idx < 0 or question_idx >= len(st["questions"]):
            return None
        q = st["questions"][question_idx]
        if q.get("type") == "decor":
            return None
        return q

    async def _mark_correct(self, event, st, target_question):
        """标记题目为已答对，返回 (True, 回复消息)"""
        if target_question.get("solved", False):
            return True, None
    
        group_id = event.get_group_id()
        if not group_id:
            group_id = f"private_{event.get_sender_id()}"
        group_id = str(group_id)

        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

        question_idx = st["questions"].index(target_question)
        idx = question_idx + 1

        # 更新题目状态
        target_question["mask"] = target_question["entry"]["title"]
        target_question["solved"] = True
        
        # 记录首次有效操作（全局监听答对也算）
        if self.gm.get_first_open_time(group_id) is None:
            self.gm.set_first_open_time(group_id, time.time())

        # ===== 1. 先发送答对消息 =====
        reply = f"答对了！第{idx}题是：{target_question['entry']['title']}"

        # 比赛模式计分
        if self.gm.is_competition_mode(group_id):
            players = self.gm.get_players(group_id)
            if players:
                scores = calculate_all_scores(players)
            first_open = self.gm.get_first_open_time(group_id)
            timestamp = time.time()
            if first_open is None:
                self.gm.set_first_open_time(group_id, timestamp)
                first_open = timestamp
            elapsed = timestamp - first_open

            self.gm.init_player_state(group_id, user_id)
            state = self.gm.update_player_state(group_id, user_id, True, timestamp)

            old_mask = target_question["mask"]
            opened_letters = sum(1 for c in old_mask if c != '*' and c != ' ')

            difficulty_multiplier = get_difficulty_multiplier(
                target_question,
                st.get("format_code_counts", {}),
                st.get("preset_id") is not None
            )

            total_opened = len(st.get("open_chars", []))
            opened_letters_multiplier = get_opened_letters_multiplier(total_opened)

            title = target_question["entry"]["title"]
            revealed_count = sum(
                1 for c in title
                if c != ' ' and is_revealed(c, st.get("open_chars", []))
            )
            question_opened_multiplier = get_question_opened_multiplier(revealed_count, title)

            time_multiplier = get_time_multiplier(elapsed)

            combo_refreshed = state.get("combo_refreshed", False)
            hotness = state.get("hotness", 1.0)
            fast_penalty_level = state.get("fast_penalty_level", 0)
            participation_count = state.get("participation_count", 0)
            tip_count = self.gm.get_tip_count(group_id)
            
            score, detail = calculate_single_score(
                combo_refreshed=combo_refreshed,
                hotness=hotness,
                fast_penalty_level=fast_penalty_level,
                participation_count=participation_count,
                difficulty_multiplier=difficulty_multiplier,
                opened_letters_multiplier=opened_letters_multiplier,
                question_opened_multiplier=question_opened_multiplier,
                time_multiplier=time_multiplier,
                tip_count=tip_count
            )

            self.gm.record_answer(
                group_id,
                user_id,
                user_name,
                question_idx,
                elapsed,
                opened_letters,
                timestamp,
                detail
            )

            score_int = math.ceil(score)
            reply += f"\n📊 本题得分：{score_int} 分"

        #保存游戏
        self.gm.save()

        # 发送答对消息
        await event.send(event.plain_result(reply))

        # ===== 检查是否全部完成 =====
        all_done = all(q.get("solved", True) for q in st["questions"] if q.get("type") != "decor")

        if all_done:
            # 全部完成，直接发送完成消息（含完整答案）
            await send_question_board(event, st, "🎉 全部完成！全部答案如下：")

            preset_id = self.gm.get_preset_id(group_id)
            if preset_id is not None:
                from .preset_manager import update_preset_leaderboard
                players = self.gm.get_players(group_id)
                if players:
                    scores = calculate_all_scores(players)
                    total_score = scores.get(user_id, 0)
                    if not self.gm.is_competition_mode(group_id):
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

            if self.gm.is_competition_mode(group_id):
                players = self.gm.get_players(group_id)
                if players:
                    scores = calculate_all_scores(players)
                    ranking = sorted(scores.items(), key=lambda x: x[1], reverse=True)
                    lines = ["🏆 排行榜："]
                    for rank_idx, (uid, score) in enumerate(ranking, 1):
                        name = players[uid].get("name", uid)
                        lines.append(f"#{rank_idx}  {name}  {score}")
                    await event.send(event.plain_result("\n".join(lines)))

            self.gm.end_game(group_id)

        else:
            # 未完成，发送普通题面
            await send_question_board(event, st, "")

        return True, None

    async def _silent_guess(self, event, st, guess_text, user_id):
        """静默猜题：只判对，不判错"""
        if not guess_text:
            return False, None

        unsolved = [q for q in st["questions"] if q.get("type") != "decor" and not q.get("solved", False)]
        if not unsolved:
            return False, None

        target_question = None

        # 阶段1：普通匹配（曲名/别名精确匹配）
        for q in unsolved:
            entry = q["entry"]
            aliases = get_shared_aliases(entry["title"], self.bank_manager, user_id)
            candidates = [entry["title"]] + aliases
            if match_answer(guess_text, candidates):
                target_question = q
                break
            
        # 阶段2：字符串相似度匹配
        if target_question is None:

            best_question = None
            best_similarity = 0.0
            best_candidate = None

            for q in unsolved:
                entry = q["entry"]

                aliases = get_shared_aliases(
                    entry["title"],
                    self.bank_manager,
                    user_id
                )

                candidates = [entry["title"]] + aliases

                for candidate in candidates:
                    similarity = calculate_similarity(
                        guess_text,
                        candidate
                    )

                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_question = q
                        best_candidate = candidate

            # ===== 字符相似度日志 =====
            if best_question is not None:
                hit = best_similarity >= STRING_SIMILARITY_THRESHOLD

                logger.info(
                    f"[开字母] 字符相似度判定 | "
                    f"输入={guess_text!r} | "
                    f"最佳匹配={best_candidate!r} | "
                    f"对应题目={best_question['entry']['title']!r} | "
                    f"相似度={best_similarity:.1f}% | "
                    f"阈值={STRING_SIMILARITY_THRESHOLD}% | "
                    f"命中={'是' if hit else '否'}"
                )

            if best_similarity >= STRING_SIMILARITY_THRESHOLD:
                target_question = best_question

        # 阶段3：LLM 匹配（复用 llm_match）
        if target_question is None:
            
            logger.info(
                f"[开字母] 字符相似度未命中，进入 LLM 判定 | "
                f"输入={guess_text!r}"
            )
            
            # 全部题目都送进去，已答出的打标记，题号用板上的真实编号，
            # 免得未解列表重新排序后模型回报的题号对不上
            all_entries = []

            for question_no, q in enumerate(st["questions"], 1):
                if q.get("type") == "decor":
                    continue

                entry = q["entry"]

                aliases = get_shared_aliases(
                    entry["title"],
                    self.bank_manager,
                    user_id
                )

                all_entries.append({
                    "number": question_no,
                    "title": entry["title"],
                    "aliases": aliases,
                    "solved": bool(q.get("solved", False))
                })

            try:
                status, target_entry = await llm_match(
                    self.context,
                    event,
                    guess_text,
                    all_entries,
                    provider_id=self.llm_matcher_provider_id
                )

                # 模型说这题已经答过了：静默猜题不吭声，也不扣分
                if status == "solved":
                    logger.info(
                        f"[开字母] LLM 判定为已答出的题 | 输入={guess_text!r}"
                    )
                    return False, None

                if status == "match" and target_entry is not None:
                    target_no = target_entry.get("number")
                    for question_no, q in enumerate(st["questions"], 1):
                        if q.get("type") == "decor" or q.get("solved", False):
                            continue
                        if question_no == target_no:
                            target_question = q
                            break
            except Exception as e:
                logger.error(f"静默LLM匹配异常：{repr(e)}")

        if target_question is None:
            # 比赛模式下，答错要扣分/断连击
            group_id = event.get_group_id()
            if not group_id:
                group_id = f"private_{event.get_sender_id()}"
            group_id = str(group_id)
            if self.gm.is_competition_mode(group_id):
                self.gm.update_player_state(
                    group_id,
                    user_id,
                    False,
                    time.time()
                )
            return False, None

        await self._mark_correct(event, st, target_question)
        return True, None

    async def handle_message(self, event, st):
        text = event.message_str.strip()
        user_id = event.get_sender_id()

        idx, guess_content = self.extract_guess_content(text)
        if idx is None:
            return False, None
        
        # 只发一个数字（没有实际内容），不算回答
        if not guess_content:
            return False, None

        total_questions = len([q for q in st["questions"] if q.get("type") != "decor"])
        q = self._find_question_by_index(st, idx)

        # 情况1：序号超出范围 → 传 text（包含序号）
        if idx > total_questions or idx < 1:
            return await self._silent_guess(event, st, text, user_id)

        # 情况2：序号对应的题目不存在或已解决 → 静默（不进入 LLM）
        if q is None or q.get("solved", False):
            return False, None

        # 情况3：序号有效且题目未完成
        entry = q["entry"]
        aliases = get_shared_aliases(entry["title"], self.bank_manager, user_id)
        candidates = [entry["title"]] + aliases

        if match_answer(guess_content, candidates) or match_answer(text, candidates):
            await self._mark_correct(event, st, q)
            return True, None

        # 序号有效但匹配失败 → 进入 LLM，传 text（包含序号）
        return await self._silent_guess(event, st, text, user_id)
