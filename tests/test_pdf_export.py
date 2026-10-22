from services.pdf_export import report_to_pdf


def test_pdf_export_returns_pdf_bytes():
    pdf = report_to_pdf(
        title="Test report",
        question="What is RAG?",
        answer="## Answer\nRAG retrieves evidence and generates an answer.",
        web_sources=[{"title": "Example source", "url": "https://example.com"}],
        document_name="test.pdf"
    )
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 500
