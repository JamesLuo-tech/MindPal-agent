"""Fish Audio TTS 服务。"""
import httpx
from app.config import get_settings

FISH_AUDIO_TTS_URL = "https://api.fish.audio/v1/tts"
MAX_TEXT_LENGTH = 1000


async def synthesize_speech(text: str) -> bytes:
    """调用 Fish Audio TTS API，返回 mp3 音频字节。"""
    settings = get_settings()
    if not settings.fish_audio_api_key or not settings.fish_audio_voice_id:
        raise ValueError("Fish Audio API key 或 Voice ID 未配置")

    text = text[:MAX_TEXT_LENGTH]

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            FISH_AUDIO_TTS_URL,
            headers={
                "Authorization": f"Bearer {settings.fish_audio_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "reference_id": settings.fish_audio_voice_id,
                "format": "mp3",
                "latency": "normal",
                "normalize": True,
            },
        )
        resp.raise_for_status()
        return resp.content
