"""把问诊摘要渲染成一份正式报告样式的 PDF。

用 reportlab（纯 Python，没有系统级依赖）而不是 weasyprint——
weasyprint 底层要连 Pango/GObject，Windows 下 pip 装不全，还得额外装
GTK3 运行时；reportlab 自带 CJK 内置字体（STSong-Light），不用装字体
文件就能正常渲染中文，装完 pip 包直接能用，不给"这个项目能不能在
一台新机器上跑起来"这件事增加任何额外的系统安装步骤。

纯函数：只吃 AppointmentSummaryOut 这一个已经算好的数据对象，不碰
DB/Redis——好在不起数据库的情况下测试 PDF 内容对不对。
"""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.schemas.summary import AppointmentSummaryOut

_FONT_NAME = "STSong-Light"
if _FONT_NAME not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(UnicodeCIDFont(_FONT_NAME))

# 报告用色——克制、偏中性，面向的是要拿去给医生/咨询师看的文档，
# 不是聊天界面那套暖色调人设，正式场合优先保证可读性和打印友好。
_INK = colors.HexColor("#1f2937")
_INK_SOFT = colors.HexColor("#6b7280")
_ACCENT = colors.HexColor("#0f766e")
_RULE = colors.HexColor("#d1d5db")

_STYLES = {
    "title": ParagraphStyle(
        "title", fontName=_FONT_NAME, fontSize=20, leading=26, textColor=_INK, spaceAfter=2 * mm,
    ),
    "subtitle": ParagraphStyle(
        "subtitle", fontName=_FONT_NAME, fontSize=10, leading=14, textColor=_INK_SOFT,
    ),
    "section_heading": ParagraphStyle(
        "section_heading", fontName=_FONT_NAME, fontSize=13, leading=18, textColor=_ACCENT,
        spaceBefore=6 * mm, spaceAfter=3 * mm,
    ),
    "body": ParagraphStyle(
        "body", fontName=_FONT_NAME, fontSize=11, leading=17, textColor=_INK,
    ),
    "bullet": ParagraphStyle(
        "bullet", fontName=_FONT_NAME, fontSize=11, leading=17, textColor=_INK,
        leftIndent=4 * mm, spaceAfter=2 * mm,
    ),
    "footer": ParagraphStyle(
        "footer", fontName=_FONT_NAME, fontSize=8.5, leading=12, textColor=_INK_SOFT,
    ),
    "empty": ParagraphStyle(
        "empty", fontName=_FONT_NAME, fontSize=11, leading=17, textColor=_INK_SOFT,
    ),
}


def generate_appointment_summary_pdf(summary: AppointmentSummaryOut) -> bytes:
    """渲染成正式报告样式的 PDF 字节内容。"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=22 * mm, bottomMargin=18 * mm, leftMargin=20 * mm, rightMargin=20 * mm,
        title="MindPal 问诊摘要报告",
    )

    story = []

    story.append(Paragraph("问诊摘要报告", _STYLES["title"]))
    story.append(Paragraph("MindPal · 心理陪伴自我记录整理", _STYLES["subtitle"]))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=_ACCENT, spaceAfter=4 * mm))

    meta_table = Table(
        [
            ["统计周期", summary.period],
            ["生成时间", summary.generated_at.strftime("%Y-%m-%d %H:%M")],
        ],
        colWidths=[28 * mm, 130 * mm],
    )
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), _INK_SOFT),
        ("TEXTCOLOR", (1, 0), (1, -1), _INK),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
    ]))
    story.append(meta_table)

    story.append(Paragraph("自我记录概要", _STYLES["section_heading"]))
    if summary.bullets:
        for bullet in summary.bullets:
            story.append(Paragraph(f"●&nbsp;&nbsp;{bullet}", _STYLES["bullet"]))
    else:
        story.append(Paragraph("这段时间的记录还不够多，暂时没有能得出明确结论的要点。", _STYLES["empty"]))

    if summary.discuss_topics:
        story.append(Paragraph("本次想重点讨论", _STYLES["section_heading"]))
        story.append(Paragraph(summary.discuss_topics, _STYLES["body"]))

    story.append(Spacer(1, 10 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_RULE, spaceAfter=3 * mm))
    story.append(Paragraph(
        "本报告基于用户在 MindPal 中的自我记录（心情、睡眠、小步行动完成情况等）自动整理生成，"
        "全部内容来自用户自己填写的数据，不包含任何 AI 生成或推测的判断，"
        "仅供医生/心理咨询师了解情况参考，不构成医学诊断或治疗建议。",
        _STYLES["footer"],
    ))

    doc.build(story)
    return buffer.getvalue()
