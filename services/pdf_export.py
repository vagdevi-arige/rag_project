from io import BytesIO
from xml.sax.saxutils import escape
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer


def report_to_pdf(title, question, answer, web_sources, document_name):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=.65*inch, leftMargin=.65*inch,
                            topMargin=.65*inch, bottomMargin=.65*inch, title=title)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="AppTitle", parent=styles["Title"], textColor=colors.HexColor("#1d4ed8"), spaceAfter=14))
    styles.add(ParagraphStyle(name="AppBody", parent=styles["BodyText"], fontSize=9, leading=13, spaceAfter=7))
    story = [Paragraph(escape(title), styles["AppTitle"]),
             Paragraph("<b>Question:</b> " + escape(question), styles["BodyText"]),
             Paragraph("<b>Uploaded PDF:</b> " + escape(document_name), styles["BodyText"]),
             Spacer(1, 12)]
    for line in answer.splitlines():
        line = line.strip()
        if not line:
            story.append(Spacer(1, 4))
        elif line.startswith("### "):
            story.append(Paragraph(escape(line[4:]), styles["Heading3"]))
        elif line.startswith("## "):
            story.append(Paragraph(escape(line[3:]), styles["Heading2"]))
        elif line.startswith("# "):
            story.append(Paragraph(escape(line[2:]), styles["Heading1"]))
        else:
            line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
            story.append(Paragraph(escape(line), styles["AppBody"]))
    if web_sources:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Web sources", styles["Heading2"]))
        for i, source in enumerate(web_sources, 1):
            story.append(Paragraph(escape(f"[W{i}] {source['title']} — {source['url']}"), styles["AppBody"]))
    doc.build(story)
    return buffer.getvalue()
