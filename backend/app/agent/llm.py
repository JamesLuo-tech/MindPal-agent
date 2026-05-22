from langchain_openai import ChatOpenAI
from app.config import get_settings

_llm: ChatOpenAI | None = None


def get_llm() -> ChatOpenAI:
    """返回配置好的 DeepSeek LLM 实例（单例）。"""
    global _llm
    if _llm is None:
        settings = get_settings()
        _llm = ChatOpenAI(
            model="deepseek-chat",
            openai_api_key=settings.deepseek_api_key,
            openai_api_base=settings.deepseek_base_url,
            temperature=1.0,
            max_tokens=500,
            streaming=True,
            frequency_penalty=0.5,
        )
    return _llm
