def build_question_board(st):

    result = (
        "guessed: "
        + "".join(
            st.get(
                "open_chars",
                []
            )
        )
        + "\n"
    )

    for i, q in enumerate(
        st["questions"],
        1
    ):

        # 装饰行
        if q.get("type") == "decor":

            result += (
                f"{i}. "
                f"{q['text']}\n"
            )

            continue
        
        #普通题目
        result += (
            f"{i}. "
            f"{q['mask']}\n"
        )

    return result