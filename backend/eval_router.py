"""
路由分类离线评测 —— 拿人工标注的 app/agent/router_eval_cases.json 跑真实
router_node（真调 LLM，不 mock），核对预测的意图段和人工标注的期望是否一致，
用混淆矩阵定位容易混淆的类别。

跟单元测试的区别：单元测试（tests/test_multi_agent.py、tests/test_multi_intent.py）
mock 掉 LLM，测的是"控制流对不对"（危机词命中该不该短路、拆分格式解析对不对）；
这个脚本测的是"分类本身准不准"，必须用真实 LLM 调用，属于同一套模式在
eval_rag.py 里已经验证过——人工标注集 + 脚本化跑分 + 固定测试集做回归。

每条用例跑 SAMPLES_PER_CASE 次而不是跑一次就下结论——router 用的
get_llm() 是 temperature=1.0，不是确定性输出。第一版脚本只跑一次，
结果显示 action_06/action_07 两条"错了"，但抽样多跑几次发现其实是
40%~60% 的临界案例，单次结果基本是抛硬币，据此判断"改坏了/改好了"
会得出不可靠的结论，所以改成跑 N 次报通过率，而不是单次二元判断。

用法：
    cd backend
    python eval_router.py
"""
import asyncio
import io
import json
import sys

# Windows 下重定向到文件时，stdout 默认走系统 ANSI 代码页（GBK），
# 编码不了符号会直接崩——强制成 UTF-8，一劳永逸。
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")

from collections import Counter
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.graph import router_node

CASES_FILE = Path("app/agent/router_eval_cases.json")
OUT_FILE = Path("router_eval_result.csv")

LABELS = ("empathy", "knowledge", "action")
SAMPLES_PER_CASE = 3  # 每条用例跑几次；危机用例走关键词短路不调 LLM，跑几次都一样、开销可忽略


def _build_messages(case: dict) -> list:
    messages = []
    for turn in case.get("history", []):
        cls = HumanMessage if turn["role"] == "user" else AIMessage
        messages.append(cls(content=turn["content"]))
    messages.append(HumanMessage(content=case["message"]))
    return messages


async def _run_once(case: dict) -> dict:
    state = {
        "messages": _build_messages(case),
        "user_id": "eval-user",
        "conversation_id": "eval-convo",
        "long_term_memory": "",
        "crisis_triggered": False,
        "agent_type": "",
    }
    result = await router_node(state)
    predicted_types = [s["agent_type"] for s in result.get("intent_segments", [])]
    return {
        "predicted_types": predicted_types,
        "crisis_predicted": result.get("crisis_triggered", False),
    }


async def _run_case(case: dict) -> dict:
    expected_types = case["expected_agent_types"]
    expect_crisis = case.get("expect_crisis", False)

    runs = await asyncio.gather(*(_run_once(case) for _ in range(SAMPLES_PER_CASE)))

    types_hits = sum(sorted(r["predicted_types"]) == sorted(expected_types) for r in runs)
    crisis_hits = sum(r["crisis_predicted"] == expect_crisis for r in runs)

    return {
        "id": case["id"],
        "message": case["message"],
        "note": case.get("note", ""),
        "expected_types": expected_types,
        "expect_crisis": expect_crisis,
        "runs": runs,
        "types_pass_rate": types_hits / SAMPLES_PER_CASE,
        "crisis_pass_rate": crisis_hits / SAMPLES_PER_CASE,
    }


def _category_of(case_id: str) -> str:
    return case_id.rsplit("_", 1)[0]


async def main():
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    print(f"共 {len(cases)} 条标注用例，每条跑 {SAMPLES_PER_CASE} 次，开始跑真实 router_node...\n")

    results = []
    for i, case in enumerate(cases, 1):
        r = await _run_case(case)
        results.append(r)
        rate = r["types_pass_rate"]
        mark = "OK " if rate == 1.0 else ("MIX" if rate > 0 else "X  ")
        types_seen = [run["predicted_types"] for run in r["runs"]]
        print(f"  [{i}/{len(cases)}] {mark} {r['types_pass_rate']:.0%} {case['id']}: {types_seen}")

    print("\n── 总体通过率（每条用例的通过率取平均，不是单次二元判断）──")
    total = len(results)
    avg_types_rate = sum(r["types_pass_rate"] for r in results) / total
    avg_crisis_rate = sum(r["crisis_pass_rate"] for r in results) / total
    fully_pass = sum(r["types_pass_rate"] == 1.0 for r in results)
    print(f"  意图标签平均通过率: {avg_types_rate:.1%}")
    print(f"  危机检测平均通过率: {avg_crisis_rate:.1%}")
    print(f"  {SAMPLES_PER_CASE} 次全对的用例:  {fully_pass}/{total}")

    print("\n── 按类别分组的平均通过率 ──────────────────")
    by_category: dict[str, list[dict]] = {}
    for r in results:
        by_category.setdefault(_category_of(r["id"]), []).append(r)
    for cat, rs in by_category.items():
        rate = sum(r["types_pass_rate"] for r in rs) / len(rs)
        print(f"  {cat:20s}: {rate:.0%}")

    # 混淆矩阵：只用"期望单段"的用例，把每条用例的每一次采样（如果那次预测
    # 也是单段）都算进去，而不是只取一次结果——N 倍的数据点，统计意义更可靠，
    # 而且天然能反映出临界案例的分布（比如 60% 落 action、40% 落 empathy）。
    print("\n── 混淆矩阵（仅单意图用例，每次采样都计入，行=期望，列=预测）──")
    matrix = {t: Counter() for t in LABELS}
    single_sample_count = 0
    for r in results:
        if len(r["expected_types"]) != 1:
            continue
        expected = r["expected_types"][0]
        for run in r["runs"]:
            if len(run["predicted_types"]) == 1:
                matrix[expected][run["predicted_types"][0]] += 1
                single_sample_count += 1

    header = "          " + "".join(f"{l:>10}" for l in LABELS)
    print(header)
    for true_label in LABELS:
        row = "".join(f"{matrix[true_label][pred]:>10}" for pred in LABELS)
        print(f"{true_label:>10}" + row)
    print(f"（矩阵里共 {single_sample_count} 个采样点）")

    print("\n── 多意图用例单独看（每次采样的标签集合）──────")
    multi_expected = [r for r in results if len(r["expected_types"]) > 1]
    for r in multi_expected:
        rate = r["types_pass_rate"]
        mark = "OK " if rate == 1.0 else ("MIX" if rate > 0 else "X  ")
        types_seen = [run["predicted_types"] for run in r["runs"]]
        print(f"  {mark} {r['id']}: 期望{r['expected_types']} | 各次采样{types_seen}")

    print("\n── 通过率低于 100% 的用例（人工复核用）──────")
    imperfect = [r for r in results if r["types_pass_rate"] < 1.0 or r["crisis_pass_rate"] < 1.0]
    if not imperfect:
        print("  没有")
    for r in imperfect:
        print(f"  [{r['id']}] {r['message']}")
        print(f"      期望: {r['expected_types']} | 标签通过率: {r['types_pass_rate']:.0%} | "
              f"各次采样: {[run['predicted_types'] for run in r['runs']]}")
        if r["note"]:
            print(f"      备注: {r['note']}")

    import csv
    with open(OUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "id", "message", "expected_types", "types_pass_rate",
            "crisis_pass_rate", "sample_predictions", "note",
        ])
        writer.writeheader()
        for r in results:
            writer.writerow({
                "id": r["id"], "message": r["message"],
                "expected_types": "|".join(r["expected_types"]),
                "types_pass_rate": r["types_pass_rate"],
                "crisis_pass_rate": r["crisis_pass_rate"],
                "sample_predictions": " ; ".join(
                    "+".join(run["predicted_types"]) for run in r["runs"]
                ),
                "note": r["note"],
            })
    print(f"\n详细结果已保存到 {OUT_FILE.resolve()}")


asyncio.run(main())
