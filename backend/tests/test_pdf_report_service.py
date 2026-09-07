"""问诊摘要 PDF 渲染的测试——纯函数，不碰数据库。用 pypdf 把生成的 PDF
再读出来提取文字，直接断言内容对不对，不是只看"有没有崩、字节数多不多"。"""
from datetime import datetime, timezone
from io import BytesIO

from pypdf import PdfReader

from app.schemas.summary import AppointmentSummaryOut
from app.services.pdf_report_service import generate_appointment_summary_pdf


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def _summary(**overrides) -> AppointmentSummaryOut:
    defaults = dict(
        period="2026-08-24 ~ 2026-09-07",
        bullets=["情绪低落主要出现在晚上", "平均睡眠 5.8 小时"],
        discuss_topics="注意力下降和持续疲惫",
        generated_at=datetime(2026, 9, 7, 10, 30, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return AppointmentSummaryOut(**defaults)


def test_produces_a_valid_pdf():
    pdf_bytes = generate_appointment_summary_pdf(_summary())
    assert pdf_bytes.startswith(b"%PDF")  # PDF 文件魔数
    assert len(pdf_bytes) > 500  # 不是个空壳


def test_includes_period_and_generated_time():
    text = _extract_text(generate_appointment_summary_pdf(_summary()))
    assert "2026-08-24 ~ 2026-09-07" in text
    assert "2026-09-07 10:30" in text


def test_includes_every_bullet():
    summary = _summary(bullets=["要点甲", "要点乙", "要点丙"])
    text = _extract_text(generate_appointment_summary_pdf(summary))
    assert "要点甲" in text
    assert "要点乙" in text
    assert "要点丙" in text


def test_includes_discuss_topics_section_when_present():
    text = _extract_text(generate_appointment_summary_pdf(_summary(discuss_topics="注意力下降")))
    assert "本次想重点讨论" in text
    assert "注意力下降" in text


def test_omits_discuss_topics_section_when_absent():
    """没填想讨论的内容时，不该在报告里凭空出现这个章节标题。"""
    text = _extract_text(generate_appointment_summary_pdf(_summary(discuss_topics=None)))
    assert "本次想重点讨论" not in text


def test_shows_fallback_text_when_no_bullets():
    """记录不够多、bullets 为空时，报告要有说明文字，不能是一个空白章节。"""
    text = _extract_text(generate_appointment_summary_pdf(_summary(bullets=[])))
    assert "记录还不够多" in text


def test_includes_disclaimer_footer():
    """报告要明确说明数据来源和"不构成医学诊断"，这是给医生看的文档必须有的免责声明。"""
    text = _extract_text(generate_appointment_summary_pdf(_summary()))
    assert "不构成医学诊断" in text
    assert "自己填写的数据" in text
