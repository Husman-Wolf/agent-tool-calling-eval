# -*- coding: utf-8 -*-
"""跑全量用例，算通过率 + 失败归因，生成 report.md（简历上那两行数字就从这来）

跑法：
    ..\\.venv\\Scripts\\python.exe run_eval.py

    # 只想抽样 20 条快速验证（省时间省钱）
    ..\\.venv\\Scripts\\python.exe run_eval.py --limit 20

产出：
    控制台：通过率 + 四类失败统计 + 失败明细
    report.md：可以直接贴进 GitHub README 的报告
"""
import argparse
import csv
import os
import sys
import time
from collections import Counter

import agent
from checks import TYPES, check_case

HERE = os.path.dirname(os.path.abspath(__file__))


def load_cases():
    with open(os.path.join(HERE, "cases.csv"), encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    ap.add_argument("--out", default="report.md")
    args = ap.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[: args.limit]

    if not (os.environ.get("DEEPSEEK_API_KEY") or agent.API_KEY):
        print("没有 API Key。先填 agent.py 里的 API_KEY，或设置 DEEPSEEK_API_KEY")
        sys.exit(1)

    client = agent.make_client()
    rows = []
    t0 = time.time()

    for i, case in enumerate(cases, 1):
        talk = agent.Talk(client=client)
        result = None
        error = ""
        try:
            for turn in case["input"].split("||"):
                result = talk.send(turn.strip())
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            result = {"answer": "", "tool_calls": talk.tool_calls}

        problems = [("运行异常", error)] if error else check_case(case, result)
        ok = not problems
        rows.append({"case": case, "result": result, "problems": problems, "ok": ok})

        mark = "PASS" if ok else "FAIL"
        print(f"[{i:2d}/{len(cases)}] {case['id']} {mark}  {case['input'][:30]}")
        for t, d in problems:
            print(f"        - [{t}] {d}")

    passed = sum(1 for r in rows if r["ok"])
    total = len(rows)
    rate = passed / total * 100 if total else 0
    bucket = Counter(t for r in rows for t, _ in r["problems"])

    print("\n" + "=" * 60)
    print(f"用例总数：{total}")
    print(f"通过：{passed}    失败：{total - passed}")
    print(f"通过率：{rate:.1f}%")
    print(f"耗时：{time.time() - t0:.1f}s")
    print("\n失败归因：")
    for t in TYPES:
        if bucket.get(t):
            print(f"  {t}: {bucket[t]} 条")

    by_cat = {}
    for r in rows:
        c = r["case"]["category"]
        by_cat.setdefault(c, [0, 0])
        by_cat[c][1] += 1
        if r["ok"]:
            by_cat[c][0] += 1
    print("\n分类通过率：")
    for c, (p, n) in by_cat.items():
        print(f"  {c}: {p}/{n}")

    # 写报告
    lines = [
        "# Agent 工具调用测试报告", "",
        f"- 用例总数：**{total}**",
        f"- 通过 / 失败：**{passed} / {total - passed}**",
        f"- 通过率：**{rate:.1f}%**",
        f"- 耗时：{time.time() - t0:.1f}s",
        "", "## 失败归因", "",
    ]
    for t in TYPES:
        if bucket.get(t):
            lines.append(f"- {t}：{bucket[t]} 条")
    lines += ["", "## 分类通过率", ""]
    for c, (p, n) in by_cat.items():
        lines.append(f"- {c}：{p}/{n}")
    lines += ["", "## 失败明细", "", "| 用例 | 输入 | 失败类型 | 说明 |", "|---|---|---|---|"]
    for r in rows:
        if r["ok"]:
            continue
        case = r["case"]
        for t, d in r["problems"]:
            d = d.replace("|", "/")
            lines.append(f"| {case['id']} | {case['input']} | {t} | {d} |")

    out_path = os.path.join(HERE, args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n报告已写入：{out_path}")


if __name__ == "__main__":
    main()
