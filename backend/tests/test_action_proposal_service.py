"""action_proposal_service 的测试——这是这次安全修复的核心，重点测：
所有权校验、状态机（pending/confirmed/expired/cancelled）、TTL、
幂等（重复确认已 confirmed 的提议不重新执行）。全部 mock db，不连真实数据库
（真实并发行锁那部分单独在 test_action_proposal_integration.py 里用真实
数据库验证，mock 测不出真正的行锁）。
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.action_proposal_service import (
    ProposalAlreadyProcessedError,
    ProposalExpiredError,
    ProposalNotFoundError,
    confirm_proposal,
    create_proposal,
)

USER_ID = uuid4()
PROPOSAL_ID = uuid4()


def _with_transaction(db):
    """asyncpg.Connection.transaction() 是同步方法，返回一个支持 async with
    的 Transaction 对象——db 是 AsyncMock，直接调用 .transaction() 会变成
    协程而不是上下文管理器，这里手动接好 __aenter__/__aexit__。"""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=None)
    db.transaction = MagicMock(return_value=cm)
    return db


def _row(**overrides):
    base = {
        "user_id": USER_ID,
        "action": "record_mood",
        "params": {"mood": 4, "energy": None, "sleep_hours": None, "small_win": None},
        "summary": "记一笔今天的状态",
        "status": "pending",
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "result": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# create_proposal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_proposal_returns_real_id_and_expiry(mock_db):
    new_id = uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    mock_db.fetchrow = AsyncMock(return_value={"id": new_id, "expires_at": expires_at})

    result = await create_proposal(
        USER_ID, uuid4(), "record_mood", {"mood": 4}, "记一笔今天的状态", mock_db,
    )

    assert result == {"id": new_id, "expires_at": expires_at}
    args = mock_db.fetchrow.call_args.args
    assert args[1] == USER_ID
    assert args[3] == "record_mood"
    assert args[4] == {"mood": 4}  # 直接传字典，没有被手动 json.dumps 成字符串


# ---------------------------------------------------------------------------
# confirm_proposal —— 所有权
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_raises_not_found_when_no_such_proposal(mock_db):
    _with_transaction(mock_db)
    mock_db.fetchrow = AsyncMock(return_value=None)

    with pytest.raises(ProposalNotFoundError):
        await confirm_proposal(USER_ID, PROPOSAL_ID, mock_db)


@pytest.mark.asyncio
async def test_confirm_raises_not_found_when_owned_by_different_user(mock_db):
    """属于别人的提议，报的错跟"根本不存在"一样，不能泄露"这个 id 存在，
    只是不是你的"这种信息。"""
    _with_transaction(mock_db)
    other_user = uuid4()
    mock_db.fetchrow = AsyncMock(return_value=_row(user_id=other_user))

    with pytest.raises(ProposalNotFoundError):
        await confirm_proposal(USER_ID, PROPOSAL_ID, mock_db)


# ---------------------------------------------------------------------------
# confirm_proposal —— 状态机
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_is_idempotent_for_already_confirmed_proposal(mock_db):
    """重复确认同一条已经执行过的提议，直接返回上次的结果，不重新执行——
    这是真正的幂等语义，不是报错。"""
    _with_transaction(mock_db)
    cached_result = {"id": "abc", "mood": 4}
    mock_db.fetchrow = AsyncMock(return_value=_row(status="confirmed", result=cached_result))

    result = await confirm_proposal(USER_ID, PROPOSAL_ID, mock_db)

    assert result == {"action": "record_mood", "result": cached_result}
    mock_db.execute.assert_not_called()  # 不该有任何新的写入发生


@pytest.mark.asyncio
async def test_confirm_raises_already_processed_for_expired_status(mock_db):
    _with_transaction(mock_db)
    mock_db.fetchrow = AsyncMock(return_value=_row(status="expired"))

    with pytest.raises(ProposalAlreadyProcessedError) as exc_info:
        await confirm_proposal(USER_ID, PROPOSAL_ID, mock_db)
    assert exc_info.value.status == "expired"


@pytest.mark.asyncio
async def test_confirm_raises_already_processed_for_cancelled_status(mock_db):
    _with_transaction(mock_db)
    mock_db.fetchrow = AsyncMock(return_value=_row(status="cancelled"))

    with pytest.raises(ProposalAlreadyProcessedError) as exc_info:
        await confirm_proposal(USER_ID, PROPOSAL_ID, mock_db)
    assert exc_info.value.status == "cancelled"


# ---------------------------------------------------------------------------
# confirm_proposal —— TTL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_marks_expired_and_raises_when_past_ttl(mock_db):
    _with_transaction(mock_db)
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    mock_db.fetchrow = AsyncMock(return_value=_row(status="pending", expires_at=past))
    mock_db.execute = AsyncMock()

    with pytest.raises(ProposalExpiredError):
        await confirm_proposal(USER_ID, PROPOSAL_ID, mock_db)

    # 过期时要顺手把状态改成 expired，不能只是拒绝这次请求、状态留在 pending
    args = mock_db.execute.call_args.args
    assert "status = 'expired'" in args[0]
    assert args[1] == PROPOSAL_ID


# ---------------------------------------------------------------------------
# confirm_proposal —— 正常路径：真正执行 + 标记 confirmed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_executes_dispatch_and_marks_confirmed(mock_db, monkeypatch):
    _with_transaction(mock_db)
    mock_db.fetchrow = AsyncMock(return_value=_row())
    mock_db.execute = AsyncMock()

    fake_handler = AsyncMock(return_value={"id": "new-record", "mood": 4})
    monkeypatch.setattr(
        "app.services.action_proposal_service.ACTION_DISPATCH",
        {"record_mood": fake_handler},
    )

    result = await confirm_proposal(USER_ID, PROPOSAL_ID, mock_db)

    assert result == {"action": "record_mood", "result": {"id": "new-record", "mood": 4}}
    fake_handler.assert_awaited_once_with(
        USER_ID, {"mood": 4, "energy": None, "sleep_hours": None, "small_win": None}, mock_db,
    )
    update_args = mock_db.execute.call_args.args
    assert "status = 'confirmed'" in update_args[0]
    assert update_args[1] == PROPOSAL_ID
    assert update_args[2] == {"id": "new-record", "mood": 4}  # 结果直接传字典，不手动 dumps


@pytest.mark.asyncio
async def test_confirm_raises_value_error_for_unknown_action(mock_db, monkeypatch):
    _with_transaction(mock_db)
    mock_db.fetchrow = AsyncMock(return_value=_row(action="totally_made_up_action"))
    monkeypatch.setattr("app.services.action_proposal_service.ACTION_DISPATCH", {})

    with pytest.raises(ValueError, match="未知的 action"):
        await confirm_proposal(USER_ID, PROPOSAL_ID, mock_db)
