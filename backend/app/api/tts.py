"""TTS 路由：POST /api/tts"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import get_settings
from app.core.auth import get_current_user_id
from app.services.tts_service import synthesize_speech

router = APIRouter()


class TTSRequest(BaseModel):
    text: str


@router.post("/tts")
async def text_to_speech(
    body: TTSRequest,
    user_id: UUID = Depends(get_current_user_id),
):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text 不能为空")

    settings = get_settings()
    if not settings.fish_audio_api_key:
        raise HTTPException(status_code=503, detail="TTS 功能未配置")

    try:
        audio_bytes = await synthesize_speech(body.text)
    except Exception as e:
        import traceback
        print(f"[TTS ERROR] {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=502, detail=f"TTS 请求失败: {e}")

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )
