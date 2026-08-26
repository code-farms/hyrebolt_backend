import io
import zipfile

import pytest

from app.core.exceptions import InvalidInputError
from app.services.resume_text_extractor import (
    extract_text,
    sanitize_json,
    sanitize_text,
    sniff_kind,
)
from tests.resumes.fakes import RESUME_LINES, make_blank_pdf, make_docx, make_pdf


def test_sniff_requires_extension_and_magic_bytes() -> None:
    pdf = make_pdf(["x"])
    docx_bytes = make_docx(["x"])
    assert sniff_kind("cv.pdf", pdf[:1024]) == "pdf"
    assert sniff_kind("CV.DOCX", docx_bytes[:1024]) == "docx"
    # %PDF- may sit after a BOM/junk prefix but within the first KiB
    assert sniff_kind("cv.pdf", b"\xef\xbb\xbfjunk" + pdf[:1000]) == "pdf"

    for name, head in [
        ("cv.txt", b"plain text"),
        ("cv.pdf", b"not a pdf at all"),
        ("cv.docx", pdf[:1024]),  # docx name, pdf bytes
        ("cv.pdf", docx_bytes[:1024]),  # pdf name, zip bytes
        ("", pdf[:1024]),
    ]:
        with pytest.raises(InvalidInputError):
            sniff_kind(name, head)


async def test_extracts_pdf_text() -> None:
    text = await extract_text(make_pdf(RESUME_LINES), "pdf", max_chars=10000, timeout_seconds=5)
    assert "Senior Backend Engineer" in text
    assert "PostgreSQL" in text


async def test_extracts_docx_paragraphs_and_tables() -> None:
    data = make_docx(["Priya Sharma", "Python developer"], table=[["Skill", "Years"], ["Django", "4"]])
    text = await extract_text(data, "docx", max_chars=10000, timeout_seconds=5)
    assert "Python developer" in text
    assert "Django | 4" in text


async def test_blank_pdf_is_rejected_with_ocr_hint() -> None:
    with pytest.raises(InvalidInputError) as exc:
        await extract_text(make_blank_pdf(), "pdf", max_chars=10000, timeout_seconds=5)
    assert "OCR" in exc.value.message


async def test_zip_without_document_xml_is_rejected() -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(InvalidInputError) as exc:
        await extract_text(out.getvalue(), "docx", max_chars=10000, timeout_seconds=5)
    assert "PDF and DOCX" in exc.value.message


async def test_garbage_bytes_become_422_not_500() -> None:
    with pytest.raises(InvalidInputError):
        await extract_text(b"%PDF-1.4 garbage", "pdf", max_chars=10000, timeout_seconds=5)


async def test_text_is_truncated_to_max_chars() -> None:
    text = await extract_text(make_pdf(RESUME_LINES), "pdf", max_chars=20, timeout_seconds=5)
    assert len(text) == 20


def test_sanitize_strips_controls_and_collapses_whitespace() -> None:
    assert sanitize_text("A\x00B\r\n\t  C\n\n\n\nD ") == "AB\nC\n\nD"
    assert sanitize_json({"a": ["x\x00y", {"b": "z\x07"}], "n": 1}) == {"a": ["xy", {"b": "z"}], "n": 1}
