"""PDF Processing Service — parse PDF to structured text."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from app.exceptions import PDFParsingError
from app.schemas.metadata import PDFMetadata
from app.utils.logging import get_logger

logger = get_logger(__name__)

MINIMUM_CHARS_PER_PAGE = 50  # below this, try pdfplumber fallback

# If the average line length is this short, text is likely garbled (try fallback)
_GARBLED_LINE_LENGTH_THRESHOLD = 15
# Fraction of lines that must be short for text to be considered garbled
_GARBLED_LINE_FRACTION = 0.6


@dataclass
class PageContent:
    page_number: int  # 1-based
    raw_text: str
    char_count: int


@dataclass
class ParsedDocument:
    document_id: str
    pages: list[PageContent]
    pdf_metadata: PDFMetadata
    parser_used: str
    total_chars: int = field(init=False)

    def __post_init__(self) -> None:
        self.total_chars = sum(p.char_count for p in self.pages)


class PDFProcessorService:
    """Parse a PDF file into structured per-page text."""

    def parse(self, file_path: str, document_id: str) -> ParsedDocument:
        """Primary entry point. Tries PyMuPDF, falls back to pdfplumber."""
        if not os.path.exists(file_path):
            raise PDFParsingError(f"File not found: {file_path}")

        try:
            result = self._parse_pymupdf(file_path, document_id)
        except PDFParsingError:
            raise
        except Exception as exc:
            logger.warning("PyMuPDF failed (%s); trying pdfplumber", exc,
                           extra={"document_id": document_id})
            result = None

        # Decide whether PyMuPDF output is good enough
        if result is not None:
            avg_chars = result.total_chars / max(len(result.pages), 1)
            if avg_chars < MINIMUM_CHARS_PER_PAGE or self._looks_garbled(result):
                logger.info(
                    "PyMuPDF output looks poor (%.1f chars/page); trying pdfplumber",
                    avg_chars,
                    extra={"document_id": document_id},
                )
                result = None

        if result is None:
            try:
                result = self._parse_pdfplumber(file_path, document_id)
            except Exception as exc:
                raise PDFParsingError(
                    f"Both PyMuPDF and pdfplumber failed to extract text: {exc}",
                    detail=str(exc),
                ) from exc

        # If both text-based parsers produced little text, try OCR as last resort
        ocr_attempted = False
        ocr_error: str | None = None
        if result.total_chars < MINIMUM_CHARS_PER_PAGE:
            ocr_attempted = True
            try:
                ocr_result = self._parse_ocr(file_path, document_id)
                if ocr_result.total_chars >= MINIMUM_CHARS_PER_PAGE:
                    logger.info(
                        "OCR extracted %d chars from scanned PDF",
                        ocr_result.total_chars,
                        extra={"document_id": document_id},
                    )
                    result = ocr_result
            except Exception as exc:
                ocr_error = str(exc)
                logger.warning("OCR fallback failed: %s", exc, extra={"document_id": document_id})

        if result.total_chars < MINIMUM_CHARS_PER_PAGE:
            if ocr_attempted and ocr_error:
                hint = (
                    "OCR was attempted but failed (poppler/tesseract may not be installed). "
                    f"OCR error: {ocr_error}"
                )
            else:
                hint = "Please use a text-based PDF or install tesseract-ocr and poppler-utils."
            raise PDFParsingError(
                "PDF contains no extractable text. It appears to be a scanned image-only PDF. "
                + hint,
                detail=f"Total chars extracted: {result.total_chars}",
            )

        logger.info(
            "Parsed %d pages, %d chars using %s",
            len(result.pages),
            result.total_chars,
            result.parser_used,
            extra={"document_id": document_id},
        )
        return result

    # ------------------------------------------------------------------
    # Quality check
    # ------------------------------------------------------------------

    def _looks_garbled(self, result: ParsedDocument) -> bool:
        """Return True if the extracted text looks like garbled stream-order text."""
        all_lines = []
        for page in result.pages:
            all_lines.extend(page.raw_text.splitlines())

        non_empty = [l for l in all_lines if l.strip()]
        if len(non_empty) < 5:
            return False  # too few lines to judge

        short_lines = sum(1 for l in non_empty if len(l.strip()) < _GARBLED_LINE_LENGTH_THRESHOLD)
        fraction = short_lines / len(non_empty)
        return fraction > _GARBLED_LINE_FRACTION

    # ------------------------------------------------------------------
    # Private parsers
    # ------------------------------------------------------------------

    def _parse_pymupdf(self, file_path: str, document_id: str) -> ParsedDocument:
        import fitz  # PyMuPDF

        pages: list[PageContent] = []
        meta: dict = {}

        with fitz.open(file_path) as doc:
            if doc.is_encrypted:
                raise PDFParsingError("PDF is password-protected / encrypted.")

            raw_meta = doc.metadata or {}
            meta = {
                "title": raw_meta.get("title"),
                "author": raw_meta.get("author"),
                "creation_date": raw_meta.get("creationDate"),
                "producer": raw_meta.get("producer"),
            }

            for i, page in enumerate(doc):
                # sort=True: read text top-to-bottom, left-to-right (fixes multi-column CVs)
                text = page.get_text("text", sort=True)

                # Also extract text from annotations (some PDFs use free-text annotations)
                annot_texts: list[str] = []
                for annot in page.annots():
                    annot_info = annot.info
                    if annot_info.get("content"):
                        annot_texts.append(annot_info["content"])

                if annot_texts:
                    text = text + "\n" + "\n".join(annot_texts)

                # Extract text from form fields (XFA / AcroForm)
                widget_texts: list[str] = []
                for widget in page.widgets():
                    if widget.field_value and isinstance(widget.field_value, str):
                        widget_texts.append(widget.field_value)

                if widget_texts:
                    text = text + "\n" + "\n".join(widget_texts)

                pages.append(PageContent(
                    page_number=i + 1,
                    raw_text=text,
                    char_count=len(text),
                ))

        pdf_metadata = PDFMetadata(
            title=meta.get("title"),
            author=meta.get("author"),
            creation_date=meta.get("creation_date"),
            producer=meta.get("producer"),
            page_count=len(pages),
            file_size_bytes=os.path.getsize(file_path),
            parser_used="pymupdf",
        )
        return ParsedDocument(
            document_id=document_id,
            pages=pages,
            pdf_metadata=pdf_metadata,
            parser_used="pymupdf",
        )

    def _parse_pdfplumber(self, file_path: str, document_id: str) -> ParsedDocument:
        import pdfplumber

        pages: list[PageContent] = []

        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                # x_tolerance / y_tolerance help with multi-column and tabular layouts
                text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""

                # If still empty, try extracting word-by-word and joining
                if not text.strip():
                    words = page.extract_words(x_tolerance=2, y_tolerance=2)
                    if words:
                        text = _words_to_text(words)

                pages.append(PageContent(
                    page_number=i + 1,
                    raw_text=text,
                    char_count=len(text),
                ))

        pdf_metadata = PDFMetadata(
            page_count=len(pages),
            file_size_bytes=os.path.getsize(file_path),
            parser_used="pdfplumber",
        )
        return ParsedDocument(
            document_id=document_id,
            pages=pages,
            pdf_metadata=pdf_metadata,
            parser_used="pdfplumber",
        )


    def _parse_ocr(self, file_path: str, document_id: str) -> ParsedDocument:
        """OCR fallback for scanned/image-only PDFs using pytesseract + pdf2image."""
        import sys
        import pytesseract
        from pdf2image import convert_from_path

        # Windows: set explicit paths if the tools are not on PATH
        if sys.platform == "win32":
            import shutil
            if not shutil.which("tesseract"):
                pytesseract.pytesseract.tesseract_cmd = (
                    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
                )
            _poppler_path = (
                r"C:\poppler\poppler-24.08.0\Library\bin"
                if not shutil.which("pdftoppm") else None
            )
        else:
            _poppler_path = None

        pages: list[PageContent] = []
        images = convert_from_path(file_path, dpi=200, poppler_path=_poppler_path)
        for i, img in enumerate(images):
            text = pytesseract.image_to_string(img) or ""
            pages.append(PageContent(
                page_number=i + 1,
                raw_text=text,
                char_count=len(text),
            ))

        pdf_metadata = PDFMetadata(
            page_count=len(pages),
            file_size_bytes=os.path.getsize(file_path),
            parser_used="ocr",
        )
        return ParsedDocument(
            document_id=document_id,
            pages=pages,
            pdf_metadata=pdf_metadata,
            parser_used="ocr",
        )


def _words_to_text(words: list[dict]) -> str:
    """Reconstruct readable text from pdfplumber word dicts, grouped by line."""
    if not words:
        return ""
    # Sort by top (y), then x0
    words = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
    lines: list[list[str]] = []
    current_y: float | None = None
    current_line: list[str] = []
    tolerance = 3  # pixels — words within this y-range are on the same line

    for w in words:
        y = round(w["top"])
        if current_y is None or abs(y - current_y) > tolerance:
            if current_line:
                lines.append(current_line)
            current_line = [w["text"]]
            current_y = y
        else:
            current_line.append(w["text"])

    if current_line:
        lines.append(current_line)

    return "\n".join(" ".join(line) for line in lines)
