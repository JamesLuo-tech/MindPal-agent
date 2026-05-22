from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

# config.py 在 backend/app/，往上两级就是项目根目录的 .env
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    serpapi_key: str = ""
    fish_audio_api_key: str = ""
    fish_audio_voice_id: str = ""

    class Config:
        env_file = str(_ENV_FILE)
        env_file_encoding = "utf-8"
        extra = "ignore"  # 忽略 VITE_* 等前端变量


@lru_cache()
def get_settings() -> Settings:
    return Settings()
