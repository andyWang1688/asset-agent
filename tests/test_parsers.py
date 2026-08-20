import io

from reportlab.pdfgen import canvas

from app.ingest.parsers import parse_upload


def test_txt():
    kind, text = parse_upload("a.md", "hello 世界".encode(), 10)
    assert kind == "text" and "hello" in text


def test_pdf():
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, "password=abc12345 project demo")
    c.save()
    kind, text = parse_upload("doc.pdf", buf.getvalue(), 10)
    assert kind == "pdf"
    assert "password=abc12345" in text


def test_reject_unknown():
    try:
        parse_upload("a.docx", b"xx", 10)
        assert False
    except ValueError:
        pass
