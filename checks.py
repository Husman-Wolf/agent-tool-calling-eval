# -*- coding: utf-8 -*-
"""用例断言逻辑：pytest 和 run_eval.py 共用同一套判定，避免两边口径不一致。

check_case 返回空列表 = 通过；否则返回 [(失败类型, 说明), ...]
失败类型固定四类，正好对应简历上要写的「四类失败归因」：
    工具误调 / 工具选错 / 参数错误 / 回答不符
"""

TYPES = ("工具误调", "工具选错", "参数错误", "回答不符", "运行异常")


def _same(got, want):
    """参数比较：能当数字比就比数字，否则比字符串。"""
    try:
        return abs(float(got) - float(want)) < 1e-6
    except (TypeError, ValueError):
        return str(got).strip() == str(want).strip()


def check_case(case, result):
    problems = []
    calls = result.get("tool_calls") or []
    names = [c["name"] for c in calls]
    answer = result.get("answer") or ""

    expect_no_tools = str(case.get("expect_no_tools", "")).strip() == "1"
    expect_tools = [t.strip() for t in str(case.get("expect_tools", "")).split("|") if t.strip()]

    # 1) 不该调工具却调了
    if expect_no_tools and names:
        problems.append(("工具误调", f"不该调工具，实际调用了 {names}"))

    # 2) 该调的工具没调到
    for t in expect_tools:
        if t not in names:
            problems.append(("工具选错", f"期望调用 {t}，实际是 {names or '没调任何工具'}"))

    # 3) 参数对不对：只要「某一次调用」同时满足全部 k=v 就算过
    #    （不能把所有调用的参数合并起来比，多目标场景会互相覆盖）
    raw_args = str(case.get("expect_args", "")).strip()
    if raw_args:
        pairs = []
        for pair in raw_args.split(";"):
            if not pair.strip():
                continue
            k, _, v = pair.partition("=")
            pairs.append((k.strip(), v.strip()))

        hit = False
        for c in calls:
            args = c.get("args") or {}
            if all(k in args and _same(args[k], v) for k, v in pairs):
                hit = True
                break

        if not hit:
            actual = [c.get("args") for c in calls] or "没有调用"
            problems.append(("参数错误", f"没有任何一次调用满足 {raw_args}（实际 {actual}）"))

    # 4) 回答里必须有 / 绝不能有的关键词（多个用 | 表示"任意一个"）
    want_words = [w.strip() for w in str(case.get("contains", "")).split("|") if w.strip()]
    if want_words and not any(w in answer for w in want_words):
        problems.append(("回答不符", f"回答里没有 {' 或 '.join(want_words)}"))

    ban_words = [w.strip() for w in str(case.get("not_contains", "")).split("|") if w.strip()]
    for w in ban_words:
        if w in answer:
            problems.append(("回答不符", f"回答里出现了不该有的「{w}」"))

    return problems
