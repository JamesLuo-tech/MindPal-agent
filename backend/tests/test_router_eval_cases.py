"""router_eval_cases.json 本身的结构校验——不跑真实 LLM（那是 eval_router.py
的事），只保证标注集本身格式对，坏掉的标注数据不会悄悄拖累 eval_router.py
跑出一堆看不懂的报错。"""
import json
from pathlib import Path

CASES_FILE = Path(__file__).parent.parent / "app" / "agent" / "router_eval_cases.json"
VALID_LABELS = {"empathy", "knowledge", "action"}


def _load_cases():
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))


def test_cases_file_is_valid_json_and_non_empty():
    cases = _load_cases()
    assert isinstance(cases, list)
    assert len(cases) >= 20  # 太少就没法算出有意义的混淆矩阵


def test_case_ids_are_unique():
    cases = _load_cases()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "存在重复的用例 id"


def test_every_case_has_required_fields():
    cases = _load_cases()
    for c in cases:
        assert "id" in c and c["id"]
        assert "message" in c and c["message"]
        assert "expected_agent_types" in c
        assert "expect_crisis" in c and isinstance(c["expect_crisis"], bool)


def test_expected_agent_types_are_valid_and_non_empty():
    cases = _load_cases()
    for c in cases:
        types = c["expected_agent_types"]
        assert isinstance(types, list) and len(types) >= 1, f"{c['id']} 缺少期望标签"
        assert len(types) <= 2, f"{c['id']} 期望标签超过 2 个，router 最多只拆两段"
        assert all(t in VALID_LABELS for t in types), f"{c['id']} 有非法标签: {types}"


def test_history_turns_have_valid_role_and_content():
    cases = _load_cases()
    for c in cases:
        for turn in c.get("history", []):
            assert turn["role"] in ("user", "assistant"), f"{c['id']} 历史里有非法 role"
            assert turn["content"].strip(), f"{c['id']} 历史里有空内容"


def test_crisis_cases_expect_empathy_only():
    """危机用例按设计应该短路成单段 empathy，不应该标注成别的或者标成多段。"""
    cases = _load_cases()
    for c in cases:
        if c["expect_crisis"]:
            assert c["expected_agent_types"] == ["empathy"], f"{c['id']} 危机用例的期望标签应该是 ['empathy']"


def test_covers_all_three_labels_as_single_intent():
    """标注集至少要覆盖三个标签各自的单意图场景，不然混淆矩阵会有整行/整列是空的。"""
    cases = _load_cases()
    single_intent_labels = {
        c["expected_agent_types"][0]
        for c in cases
        if len(c["expected_agent_types"]) == 1 and not c["expect_crisis"]
    }
    assert single_intent_labels == VALID_LABELS


def test_covers_at_least_one_multi_intent_case():
    cases = _load_cases()
    assert any(len(c["expected_agent_types"]) == 2 for c in cases)
