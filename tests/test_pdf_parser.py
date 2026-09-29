"""PDF 解析与下载测试（用 pymupdf 现场生成测试 PDF，无需外部文件）。"""
import httpx
import pytest

from autoresearch.literature.pdf_parser import PdfParseError, download_pdf, parse_pdf


@pytest.fixture()
def sample_pdf(tmp_path):
    fitz = pytest.importorskip("pymupdf")
    path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello AutoResearch. This is a test PDF for parsing.")
    doc.save(str(path))
    doc.close()
    return path


def test_parse_pdf_roundtrip(sample_pdf):
    parsed = parse_pdf(sample_pdf)
    assert parsed["n_pages"] == 1
    assert "Hello AutoResearch" in parsed["text"]
    assert parsed["title"]  # 元数据缺标题时回退正文首行


def test_parse_pdf_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf")
    with pytest.raises(PdfParseError):
        parse_pdf(bad)


def test_download_pdf_writes_file(tmp_path, test_settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4 fake-bytes")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    dest = tmp_path / "x.pdf"
    download_pdf("http://example.org/a.pdf", dest, test_settings, client=client)
    assert dest.read_bytes().startswith(b"%PDF")


def test_download_pdf_rejects_non_pdf(tmp_path, test_settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not a pdf</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(PdfParseError):
        download_pdf("http://example.org/a.pdf", tmp_path / "y.pdf", test_settings, client=client)
