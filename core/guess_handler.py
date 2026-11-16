from astrbot.api import logger
from .matcher import match_answer, calculate_similarity
from .llm_matcher import llm_match
from .alias_manager import get_shared_aliases
from .board_builder import build_question_board
from .preset_manager import update_preset_leaderboard
from .helpers import send_question_board
from .quote import quote_send
from .scoring import (
    calculate_single_score,
    calculate_all_scores,
    get_time_multiplier,
    get_difficulty_multiplier,
    get_opened_letters_multiplier,
    get_question_opened_multiplier
)
from .utils import is_revealed
from .constants import STRING_SIMILARITY_THRESHOLD
import time
import math

class GuessHandler:
    def __init__(self, gm, bank_manager, context, llm_matcher_provider_id=""):
        self.gm = gm
        self.bank_manager = bank_manager
        self.context = context
        self.llm_matcher_provider_id = llm_matcher_provider_id

    async def handle_guess(self, event, st, guess_text, number):
        # ===== 统一 group_id =====
        group_id = event.get_group_id()
        if not group_id:
            group_id = f"private_{event.get_sender_id()}"
        group_id = str(group_id)

        # ===== 获取用户信息 =====
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

        # ===== 按序号取题 =====
        questions = st["questions"]
        if not isinstance(number, int) or number < 1 or number > len(questions):
            return True, "无效的序号。"
        target_question = questions[number - 1]
        # 装饰行不参与作答
        if target_question.get("type") == "decor":
            return True, "无效的序号。"

        # 已经答过的题：不再判，也不断连击
        if target_question.get("solved", False):
            return True, f"{guess_text} 已经答过了。"

        entry = target_question["entry"]
        aliases = get_shared_aliases(entry["title"], self.bank_manager, user_id)
        candidates = [entry["title"]] + aliases

        # ===== 第一阶段：曲名/别名精确匹配 =====
        hit = match_answer(guess_text, candidates)

        # ===== 第二阶段：字符相似度（只对这一题）=====
        if not hit:
            best_similarity = 0.0
            best_candidate = None

            for candidate in candidates:
                similarity = calculate_similarity(guess_text, candidate)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_candidate = candidate

            logger.info(
                f"[开字母] 字符相似度判定 | "
                f"输入={guess_text!r} | "
                f"最佳匹配={best_candidate!r} | "
                f"对应题目={entry['title']!r} | "
                f"相似度={best_similarity:.1f}% | "
                f"阈值={STRING_SIMILARITY_THRESHOLD}% | "
                f"命中={'是' if best_similarity >= STRING_SIMILARITY_THRESHOLD else '否'}"
            )

            hit = best_similarity >= STRING_SIMILARITY_THRESHOLD

        # ===== 第三阶段：单题 LLM 判定 =====
        llm_status = ""
        if not hit:
            logger.info(
                f"[开字母] 字符相似度未命中，进入 LLM 判定 | "
                f"输入={guess_text!r} | 第{number}题"
            )

            try:
                llm_status, _ = await llm_match(
                    self.context,
                    event,
                    guess_text,
                    {"title": entry["title"], "aliases": aliases},
                    provider_id=self.llm_matcher_provider_id
                )
                hit = llm_status == "match"
            except Exception as e:
                logger.error(f"llm_match异常：{repr(e)}")
                llm_status = "error"
                hit = False

        # ===== 没找到 =====
        if not hit:
            # -1：模型判定为与开字母无关的日常讨论，不算答错，不断连击
            if llm_status == "irrelevant":
                return True, f"{guess_text} 不在题目里。"

            # 模型异常：判不了就不判，不算答错
            if llm_status == "error":
                return True, "大模型响应失败，本次调用不判定对错。"

            # 比赛模式下，明确猜错要扣分/断连击
            if self.gm.is_competition_mode(group_id):
                self.gm.update_player_state(
                    group_id,
                    user_id,
                    False,
                    time.time()
                )
            return True, f"{guess_text} 不在题目里。"

        # ===== 答对：计算题目索引和已开字母数 =====
        question_idx = number - 1
        old_mask = target_question["mask"]
        opened_letters = sum(1 for c in old_mask if c != '*' and c != ' ')

        # 更新题目状态
        target_question["mask"] = target_question["entry"]["title"]
        target_question["solved"] = True
        idx = question_idx + 1
        solved_msg = f"答对了！第{idx}题是：{target_question['entry']['title']}"

        # ===== 比赛模式计分 =====
        score_msg = None
        if self.gm.is_competition_mode(group_id):
            players = self.gm.get_players(group_id)
            if players:
                scores = calculate_all_scores(players)
            # 1. 确保计时开始
            first_open = self.gm.get_first_open_time(group_id)
            timestamp = time.time()
            if first_open is None:
                self.gm.set_first_open_time(group_id, timestamp)
                first_open = timestamp
            elapsed = timestamp - first_open

            # 2. 初始化玩家状态（如果不存在）
            self.gm.init_player_state(group_id, user_id)

            # 3. 更新玩家状态（答题正确）
            state = self.gm.update_player_state(group_id, user_id, True, timestamp)

            # 4. 计算各项倍率
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

            score_int = math.ceil(score)
            solved_msg += f"\n📊 本题得分：{score_int} 分"

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
        #保存游戏
        self.gm.save()
        
        #发送答对消息（引用用户那条猜测，方便对照）
        await quote_send(event, solved_msg)

        # ===== 检查是否全部完成 =====
        all_done = all(q.get("solved", False) for q in st["questions"] if q.get("type") != "decor")

        if all_done:
            # 全部完成，直接发送完成消息（含完整答案）
            await send_question_board(event, st, "🎉 全部完成！全部答案如下：", quote=True)

            preset_id = self.gm.get_preset_id(group_id)
            if preset_id is not None:
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
            # 未完成，发送普通题面（同样引用这次猜测）
            await send_question_board(event, st, "", quote=True)

        return True, ""