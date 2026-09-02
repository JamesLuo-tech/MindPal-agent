from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_pool, close_pool
from app.redis_client import get_redis, close_redis
from app.api import chat, memory, report, tts, today, goals, support


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


@app.get("/health")
async def health():
    return {"status": "ok"}
