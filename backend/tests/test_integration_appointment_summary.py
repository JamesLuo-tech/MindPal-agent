"""集成测试——走真实的 FastAPI 应用 + 真实数据库连接，不 mock 任何一层。

跟这个项目里其余测试的区别：
  - 单测（test_*_service.py、test_*_tools.py 等）要么是纯函数，要么 mock
    掉了数据库/LLM，测的是"某一层自己的逻辑对不对"
  - 这份测试反过来——只 override 掉需要真实 Supabase JWT 才能过的鉴权依赖
    （测那个是另一回事，不是这个功能该测的），其余从路由注册、依赖注入、
    真实 asyncpg 查询、到 PDF 渲染，整条链路都是真实调用

这类测试能抓住单测抓不到的问题：路由到底有没有正确注册、依赖注入的类型
对不对、真实查询语句有没有语法错误、真实数据经过整条链路最终有没有正确
出现在响应里——之前 PDF 功能上线时就真的抓到过一次"新路由没注册上"的坑
（当时是端口被旧进程占了，新代码没生效），如果当时有这份测试跑一下就能
立刻发现，不用手动排查半天。

用的是这个项目里其他手工验证脚本一直在用的同一个真实测试用户：
d74fdb1f-6040-4687-abfa-1ac3b90bc62b（Supabase 项目里真实存在，有真实的
心情/日程记录）。
"""
from io import BytesIO
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from pypdf import PdfReader

import app.database as _db
from app.config import get_settings
from app.core.auth import get_current_user_id
from app.main import app

TEST_USER_ID = UUID("d74fdb1f-6040-4687-abfa-1ac3b90bc62b")


@pytest_asyncio.fixture
async def db_pool():
    """真实初始化数据库连接池——不 mock，这就是集成测试的重点。

    CI 环境目前没有配置 DATABASE_URL（backend 那份 CI job 只跑
    pip install + pytest，没给任何数据库/Supabase 密钥），这几条用例
    需要连真实数据库，硬跑会在 CI 里直接报错、拖垮整条流水线，不是"这条
    用例失败"那么简单。没配置就跳过而不是报错——本地开发者只要 .env 里
    配了 DATABASE_URL 就能正常跑这份集成测试，CI 现在跳过，以后给 CI 配
    了测试库密钥自然就会跟着跑起来。
    """
    if not get_settings().database_url:
        pytest.skip("DATABASE_URL 未配置，跳过需要真实数据库的集成测试")
    await _db.init_pool()
    yield
    await _db.close_pool()


@pytest_asyncio.fixture
async def client(db_pool):
    """真实的 ASGI 应用 + 真实数据库，只 override 掉鉴权（不然每条用例都要
    去申请一个真实 Supabase JWT，测的又不是鉴权本身）。"""
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_appointment_summary_json_endpoint_end_to_end(client):
    """整条链路：HTTP 请求 → 路由 → service 层查真实数据库 → 组装响应，
    确认真实拿到的数据能通过 Pydantic 的 response_model 校验、字段类型对。"""
    resp = await client.post(
        "/api/reports/appointment-summary",
        json={"days": 30, "discuss_topics": None},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["period"], str) and body["period"]
    assert isinstance(body["bullets"], list)
    assert all(isinstance(b, str) for b in body["bullets"])
    assert "generated_at" in body


@pytest.mark.asyncio
async def test_appointment_summary_pdf_endpoint_end_to_end(client):
    """整条链路多一段：真实数据 → PDF 渲染 → 真实 HTTP 二进制响应，
    再把响应体读回来确认请求里传的 discuss_topics 真的被渲染进了 PDF——
    不是随便返回一份写死的模板文件。"""
    resp = await client.post(
        "/api/reports/appointment-summary/pdf",
        json={"days": 30, "discuss_topics": "集成测试专用讨论点"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")

    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(resp.content)).pages)
    assert "集成测试专用讨论点" in text  # 请求参数真的流经了整条链路，渲染进了最终 PDF
    assert "不构成医学诊断" in text  # 免责声明也在真实渲染结果里


@pytest.mark.asyncio
async def test_appointment_summary_rejects_invalid_days(client):
    """Pydantic 的 ge=1, le=90 校验在真实请求路径上真的生效——不是只在
    schema 定义里写着好看。"""
    resp = await client.post(
        "/api/reports/appointment-summary",
        json={"days": 999, "discuss_topics": None},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_appointment_summary_requires_auth():
    """确认鉴权依赖是真的在生效——不是因为测试顺手 override 掉了才通过的。
    这条用例故意不用 client fixture（不 override 鉴权），验证真实请求
    在没有 Authorization header 时会被真实拒绝。

    刻意不依赖 db_pool——鉴权检查在触达任何数据库依赖之前就会短路返回
    401，不需要真实数据库，所以这条用例在没配置 DATABASE_URL 的 CI 环境
    里也能正常跑，不用被跳过。
    """
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/reports/appointment-summary", json={"days": 14})
    assert resp.status_code == 401
