import re
import time
import math
from astrbot.api import logger
from difflib import SequenceMatcher
from .matcher import match_answer
from .answer_parser import parse_numbered_answer
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

    def _find_question_by_index(self, st, idx):
        """根据序号查找题目（1-based）"""
        question_idx = idx - 1
        if question_idx < 0 or question_idx >= len(st["questions"]):
            return None
        q = st["questions"][question_idx]
        if q.get("type") == "decor":
            return None
        return q

    async def _mark_correct(self, event, st, target_question, question_idx):
        """标记题目为已答对，返回 (True, 回复消息)"""
        if target_question.get("solved", False):
            return True, None
    
        group_id = event.get_group_id()
        if not group_id:
            group_id = f"private_{event.get_sender_id()}"
        group_id = str(group_id)

        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

        idx = question_idx + 1

        # 答题前已开的字母数，必须在覆盖 mask 之前取，否则恒等于满开
        old_mask = target_question.get("mask", "")
        opened_letters = sum(1 for c in old_mask if c != '*' and c != ' ')

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
        all_done = all(q.get("solved", False) for q in st["questions"] if q.get("type") != "decor")

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

    async def handle_message(self, event, st):
        """静默作答：只认「数字 空格 正文」，判对才吭声

        - 纯曲名、1Song、1.abc、只发数字：一律不算作答，连断连击都不做
        - 序号非法（前导零、0、越界、装饰行）：同样静默不理会
        - 多行作答：不判定对错，也不改连击
        """
        text = event.message_str.strip()
        user_id = event.get_sender_id()

        status, number, content = parse_numbered_answer(
            text,
            len(st["questions"])
        )

        # 多行作答：不判定，不判对也不判错，也不断连击
        if status == "multi":
            logger.info("[开字母] 静默链路检测到多行作答，本次不判定")
            return False, None

        if status != "ok":
            return False, None

        q = self._find_question_by_index(st, number)

        # 越界、装饰行、已经答过：静默不理会
        if q is None or q.get("solved", False):
            return False, None

        entry = q["entry"]
        aliases = get_shared_aliases(entry["title"], self.bank_manager, user_id)
        candidates = [entry["title"]] + aliases

        # 阶段1：曲名/别名精确匹配
        if match_answer(content, candidates):
            await self._mark_correct(event, st, q, number - 1)
            return True, None

        # 阶段2：字符相似度
        best_similarity = 0.0
        best_candidate = None

        for candidate in candidates:
            similarity = calculate_similarity(content, candidate)
            if similarity > best_similarity:
                best_similarity = similarity
                best_candidate = candidate

        logger.info(
            f"[开字母] 静默作答字符相似度 | 输入={content!r} | "
            f"最佳匹配={best_candidate!r} | 对应题目={entry['title']!r} | "
            f"相似度={best_similarity:.1f}% | 阈值={STRING_SIMILARITY_THRESHOLD}% | "
            f"命中={'是' if best_similarity >= STRING_SIMILARITY_THRESHOLD else '否'}"
        )

        if best_similarity >= STRING_SIMILARITY_THRESHOLD:
            await self._mark_correct(event, st, q, number - 1)
            return True, None

        # 阶段3：单题 LLM 判定
        try:
            result, _ = await llm_match(
                self.context,
                event,
                content,
                {"title": entry["title"], "aliases": aliases},
                provider_id=self.llm_matcher_provider_id
            )
        except Exception as e:
            logger.error(f"静默LLM匹配异常：{repr(e)}")
            result = "error"

        if result == "match":
            await self._mark_correct(event, st, q, number - 1)
            return True, None

        # -1：模型判定为与开字母无关的日常讨论，不断连击
        if result == "irrelevant":
            logger.info("[开字母] 静默作答判定为无关讨论，不断连击")
            return False, None

        # 模型异常（空返回/格式错/超范围）：判不了就不判错
        if result == "error":
            logger.warning("[开字母] 判定失败，静默作答不判错")
            return False, None

        self._punish_silent(event)
        return False, None

    def _punish_silent(self, event):
        """静默链路答错：比赛模式下断连击，不吭声"""
        group_id = event.get_group_id()
        if not group_id:
            group_id = f"private_{event.get_sender_id()}"
        group_id = str(group_id)

        if self.gm.is_competition_mode(group_id):
            self.gm.update_player_state(
                group_id,
                event.get_sender_id(),
                False,
                time.time()
            )
            # 断连击也要落盘，否则只改了内存里的状态
            self.gm.save()
