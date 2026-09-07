from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# 必须在其余任何东西之前执行：这个项目一直是靠 pydantic-settings 自己解析
# .env（只灌进 Settings 对象，不碰 os.environ），像 LangSmith 这种直接读
# os.environ["LANGSMITH_TRACING"] 之类系统环境变量的三方 SDK 根本读不到
# .env 里的值。这里显式把 .env 加载进 os.environ，两边都能用。
# 用 __file__ 算路径而不是让 load_dotenv() 自己从当前工作目录往上找——
# 跟 app/config.py 里 _ENV_FILE 的算法保持一致，不会因为 uvicorn 从哪个
# 目录启动而找错文件。
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_pool, close_pool
from app.redis_client import get_redis, close_redis
from app.api import chat, memory, report, tts, today, goals, support, actions, summary


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    await get_redis()
    yield
    await close_pool()
    await close_redis()


app = FastAPI(title="MindPal API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(memory.router, prefix="/api", tags=["memory"])
app.include_router(report.router, prefix="/api", tags=["report"])
app.include_router(tts.router, prefix="/api", tags=["tts"])
app.include_router(today.router, prefix="/api", tags=["today"])
app.include_router(goals.router, prefix="/api", tags=["goals"])
app.include_router(support.router, prefix="/api", tags=["support"])
app.include_router(actions.router, prefix="/api", tags=["actions"])
app.include_router(summary.router, prefix="/api", tags=["summary"])


@app.get("/health")
async def health():
    return {"status": "ok"}
