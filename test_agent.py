# -*- coding: utf-8 -*-
"""pytest 入口：一条 csv = 一条用例

跑法：
    cd C:\\Users\\20532\\PyCharmMiscProject\\day08
    ..\\.venv\\Scripts\\python.exe -m pytest -v

只跑某一类：
    ..\\.venv\\Scripts\\python.exe -m pytest -v -k 参数缺失

没有 API Key 时会全部 skip，不会报错。
"""
import csv
import os

import pytest

import agent
from checks import check_case

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "cases.csv"), encoding="utf-8-sig") as f:
    CASES = list(csv.DictReader(f))

_CLIENT = [None]


def get_client():
    if _CLIENT[0] is None:
        _CLIENT[0] = agent.make_client()
    return _CLIENT[0]


def has_key():
    return bool(os.environ.get("DEEPSEEK_API_KEY") or agent.API_KEY)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case(case):
    if not has_key():
        pytest.skip("没有 API Key：填 agent.py 的 API_KEY 或设置 DEEPSEEK_API_KEY")

    talk = agent.Talk(client=get_client())
    result = None
    for turn in case["input"].split("||"):
        result = talk.send(turn.strip())

    problems = check_case(case, result)
    if problems:
        detail = "\n".join(f"[{t}] {d}" for t, d in problems)
        detail += f"\n\n实际调用：{result['tool_calls']}\n实际回答：{result['answer']}"
        pytest.fail(detail, pytrace=False)
