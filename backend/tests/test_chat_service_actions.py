"""chat_service.parse_action_proposal 的契约测试——on_tool_end 事件到
SSE action_proposal 数据的转换逻辑，纯函数，不用起 graph/DB/Redis。"""
import json
from types import SimpleNamespace

from app.services.chat_service import parse_action_proposal, should_forward_chat_stream


def test_ignores_non_action_tools():
    """lookup/recall_memory 这些知识类工具不该被当成提议。"""
    output = SimpleNamespace(content=json.dumps({"action": "x", "params": {}, "summary": "s"}))
    assert parse_action_proposal("lookup", output) is None


def test_parses_tool_message_with_content_attribute():
    """ToolNode 执行后拿到的通常是带 .content 的 ToolMessage 对象。"""
    payload = {"action": "create_micro_action", "params": {"title": "散步"}, "summary": "加一条小行动：散步"}
    output = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))

    result = parse_action_proposal("propose_create_micro_action", output)

    assert result == payload


def test_parses_plain_string_output_without_content_attribute():
    """防御性兜底：万一拿到的不是对象而是纯字符串，也不该崩。"""
    payload = {"action": "record_mood", "params": {"mood": 4}, "summary": "记一笔今天的状态"}
    output = json.dumps(payload, ensure_ascii=False)

    result = parse_action_proposal("propose_record_mood", output)

    assert result == payload


def test_returns_none_on_malformed_json_instead_of_raising():
    output = SimpleNamespace(content="不是 JSON 的一段文字")
    assert parse_action_proposal("propose_record_mood", output) is None


def test_returns_none_when_output_is_none():
    assert parse_action_proposal("propose_record_mood", None) is None


def test_returns_none_when_required_key_missing():
    output = SimpleNamespace(content=json.dumps({"action": "record_mood"}))  # 缺 params/summary
    assert parse_action_proposal("propose_record_mood", output) is None


# ---------------------------------------------------------------------------
# should_forward_chat_stream —— 单意图三个回答节点 + 多意图的 merge 该转发，
# router 自己的分类调用、多意图路径里未合并的 run_segment 中间结果不该转发。
# ---------------------------------------------------------------------------


def test_forwards_single_intent_answer_nodes():
    for node in ("empathy", "knowledge", "action"):
        assert should_forward_chat_stream(node) is True


def test_forwards_merge_node():
    """多意图合并后的最终回复该转发给用户。"""
    assert should_forward_chat_stream("merge") is True


def test_does_not_forward_router_classification_call():
    """router 自己判断 empathy/knowledge/action 的那次调用不该被当成回复转发。"""
    assert should_forward_chat_stream("router") is False


def test_does_not_forward_run_segment_intermediate_output():
    """多意图路径下，run_segment 里某一段单独的、未经合并的回答不该被用户看到，
    只有 merge 合成之后的才该转发——这是之前讨论过的一个真实风险点，
    专门写一条测试锁住这条行为，不能只靠人工检查代码。"""
    assert should_forward_chat_stream("run_segment") is False


def test_does_not_forward_unknown_or_missing_node_name():
    assert should_forward_chat_stream(None) is False
    assert should_forward_chat_stream("some_future_node") is False
