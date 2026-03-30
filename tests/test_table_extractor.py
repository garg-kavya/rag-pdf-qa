"""Tests for TableExtractorService and _rows_to_gfm helper."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.services.table_extractor import TableExtractorService, _rows_to_gfm
from app.utils.token_counter import count_tokens


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def extractor() -> TableExtractorService:
    return TableExtractorService(max_tokens=512)


# ---------------------------------------------------------------------------
# _rows_to_gfm helper
# ---------------------------------------------------------------------------

def test_rows_to_gfm_basic_structure():
    result = _rows_to_gfm(["Name", "Score"], [["Alice", "95"]])
    lines = result.splitlines()
    assert lines[0] == "| Name | Score |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| Alice | 95 |"


def test_rows_to_gfm_separator_column_count():
    header = ["A", "B", "C"]
    result = _rows_to_gfm(header, [["1", "2", "3"]])
    sep_line = result.splitlines()[1]
    assert sep_line.count("---") == len(header)


def test_rows_to_gfm_escapes_pipes():
    result = _rows_to_gfm(["Col"], [["x|y"]])
    # Pipe inside cell must be escaped so the GFM table is valid
    assert "x\\|y" in result


def test_rows_to_gfm_collapses_internal_newlines():
    result = _rows_to_gfm(["Col"], [["line1\nline2"]])
    lines = result.splitlines()
    # The data row must be a single line with the newline replaced by a space
    assert "line1 line2" in lines[2]
    assert len(lines) == 3  # header, sep, one data row


def test_rows_to_gfm_multiple_data_rows():
    result = _rows_to_gfm(["A"], [["r1"], ["r2"], ["r3"]])
    lines = result.splitlines()
    assert len(lines) == 5  # header + sep + 3 rows
    assert "r3" in lines[4]


def test_rows_to_gfm_empty_cell():
    result = _rows_to_gfm(["A", "B"], [["", "val"]])
    assert "val" in result


# ---------------------------------------------------------------------------
# _table_to_chunks — structural tests
# ---------------------------------------------------------------------------

def test_empty_table_list_returns_empty(extractor):
    assert extractor._table_to_chunks([], 1, "doc-1", "test.pdf", 0) == []


def test_table_with_header_only_returns_empty(extractor):
    # A table with only one row has no data rows
    assert extractor._table_to_chunks([["Col A", "Col B"]], 1, "doc-1", "test.pdf", 0) == []


def test_fully_empty_cells_returns_empty(extractor):
    table = [["", None], ["", ""], [None, None]]
    assert extractor._table_to_chunks(table, 1, "doc-1", "test.pdf", 0) == []


def test_simple_table_produces_one_chunk(extractor):
    table = [["Name", "Score"], ["Alice", "95"], ["Bob", "87"]]
    chunks = extractor._table_to_chunks(table, 1, "doc-1", "test.pdf", 0)
    assert len(chunks) == 1
    assert "Alice" in chunks[0].text
    assert "Bob" in chunks[0].text


def test_chunk_contains_header(extractor):
    table = [["Product", "Price"], ["Widget", "$9.99"]]
    chunks = extractor._table_to_chunks(table, 1, "doc-1", "test.pdf", 0)
    assert "Product" in chunks[0].text
    assert "Price" in chunks[0].text


def test_chunk_metadata_page_number(extractor):
    table = [["Col"], ["val"]]
    chunks = extractor._table_to_chunks(table, 5, "doc-1", "test.pdf", 0)
    assert chunks[0].page_numbers == [5]


def test_chunk_metadata_document_id(extractor):
    table = [["Col"], ["val"]]
    chunks = extractor._table_to_chunks(table, 1, "doc-99", "test.pdf", 0)
    assert chunks[0].document_id == "doc-99"


def test_chunk_metadata_document_name(extractor):
    table = [["Col"], ["val"]]
    chunks = extractor._table_to_chunks(table, 1, "doc-1", "annual_report.pdf", 0)
    assert chunks[0].document_name == "annual_report.pdf"


def test_chunk_index_starts_at_start_index(extractor):
    table = [["Col"], ["val"]]
    chunks = extractor._table_to_chunks(table, 1, "doc-1", "test.pdf", 7)
    assert chunks[0].chunk_index == 7


def test_chunk_ids_are_unique(extractor):
    # Build a table large enough to force multiple chunks
    big = "word " * 60
    table = [["A", "B"]] + [[big, big] for _ in range(20)]
    chunks = extractor._table_to_chunks(table, 1, "doc-1", "test.pdf", 0)
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_token_count_matches_text(extractor):
    table = [["Name", "Value"], ["Alice", "100"], ["Bob", "200"]]
    chunks = extractor._table_to_chunks(table, 1, "doc-1", "test.pdf", 0)
    for chunk in chunks:
        assert chunk.token_count == count_tokens(chunk.text)


def test_none_cells_normalised_to_empty_string(extractor):
    table = [["A", "B"], [None, "value"]]
    # Should not raise; None becomes ""
    chunks = extractor._table_to_chunks(table, 1, "doc-1", "test.pdf", 0)
    assert len(chunks) == 1
    assert "value" in chunks[0].text


# ---------------------------------------------------------------------------
# _table_to_chunks — large-table splitting
# ---------------------------------------------------------------------------

@pytest.fixture
def extractor_tiny() -> TableExtractorService:
    """Extractor with a very small budget so tables split quickly."""
    return TableExtractorService(max_tokens=30)


def test_large_table_produces_multiple_chunks(extractor_tiny):
    header = ["Col A", "Col B"]
    big = "word " * 10
    table = [header] + [[big, big] for _ in range(15)]
    chunks = extractor_tiny._table_to_chunks(table, 1, "doc-1", "test.pdf", 0)
    assert len(chunks) > 1


def test_header_preserved_in_every_chunk(extractor_tiny):
    header = ["Col A", "Col B"]
    big = "word " * 10
    table = [header] + [[big, big] for _ in range(15)]
    chunks = extractor_tiny._table_to_chunks(table, 1, "doc-1", "test.pdf", 0)
    for chunk in chunks:
        assert "Col A" in chunk.text
        assert "Col B" in chunk.text


def test_chunk_indices_are_sequential(extractor_tiny):
    header = ["X"]
    big = "word " * 20
    table = [header] + [[big] for _ in range(20)]
    chunks = extractor_tiny._table_to_chunks(table, 1, "doc-1", "test.pdf", 3)
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == 3 + i


def test_chunks_respect_token_budget(extractor):
    """No chunk should exceed max_tokens (except single oversized rows)."""
    big = "word " * 30
    table = [["A", "B"]] + [[big, big] for _ in range(10)]
    chunks = extractor._table_to_chunks(table, 1, "doc-1", "test.pdf", 0)
    for chunk in chunks:
        # Each chunk should be at or below budget (single-row chunks may exceed if the
        # row itself exceeds budget — that is the designed fallback behaviour)
        lines = chunk.text.splitlines()
        data_row_count = len(lines) - 2  # subtract header + sep
        if data_row_count > 1:
            assert chunk.token_count <= extractor._max_tokens


# ---------------------------------------------------------------------------
# extract() — integration tests with mocked pdfplumber
# ---------------------------------------------------------------------------

def _make_mock_pdf(pages_tables: dict[int, list]) -> MagicMock:
    """Build a mock pdfplumber PDF object with the given per-page tables."""
    mock_pages = []
    for page_num, tables in sorted(pages_tables.items()):
        mock_page = MagicMock()
        mock_page.page_number = page_num
        mock_page.extract_tables = MagicMock(return_value=tables)
        mock_pages.append(mock_page)

    mock_pdf = MagicMock()
    mock_pdf.pages = mock_pages
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    return mock_pdf


def test_extract_returns_empty_when_no_tables(extractor):
    mock_pdf = _make_mock_pdf({1: []})
    with patch("pdfplumber.open", return_value=mock_pdf):
        result = extractor.extract("any.pdf", "doc-1", "any.pdf")
    assert result == []


def test_extract_returns_chunks_for_simple_table(extractor):
    table = [["Name", "Score"], ["Alice", "95"], ["Bob", "87"]]
    mock_pdf = _make_mock_pdf({1: [table]})
    with patch("pdfplumber.open", return_value=mock_pdf):
        chunks = extractor.extract("any.pdf", "doc-1", "report.pdf")
    assert len(chunks) == 1
    assert "Alice" in chunks[0].text
    assert chunks[0].page_numbers == [1]


def test_extract_multiple_pages_each_produce_chunks(extractor):
    t1 = [["Q", "A"], ["q1", "a1"]]
    t2 = [["X", "Y"], ["x1", "y1"]]
    mock_pdf = _make_mock_pdf({1: [t1], 2: [t2]})
    with patch("pdfplumber.open", return_value=mock_pdf):
        chunks = extractor.extract("any.pdf", "doc-1", "report.pdf")
    assert len(chunks) == 2
    assert chunks[0].page_numbers == [1]
    assert chunks[1].page_numbers == [2]


def test_extract_multiple_tables_on_same_page(extractor):
    t1 = [["A"], ["1"]]
    t2 = [["B"], ["2"]]
    mock_pdf = _make_mock_pdf({1: [t1, t2]})
    with patch("pdfplumber.open", return_value=mock_pdf):
        chunks = extractor.extract("any.pdf", "doc-1", "report.pdf")
    assert len(chunks) == 2


def test_extract_start_index_applied_to_chunks(extractor):
    table = [["A", "B"], ["1", "2"]]
    mock_pdf = _make_mock_pdf({1: [table]})
    with patch("pdfplumber.open", return_value=mock_pdf):
        chunks = extractor.extract("any.pdf", "doc-1", "test.pdf", start_index=10)
    assert chunks[0].chunk_index == 10


def test_extract_document_id_and_name_on_all_chunks(extractor):
    table = [["Col"], ["val"]]
    mock_pdf = _make_mock_pdf({1: [table]})
    with patch("pdfplumber.open", return_value=mock_pdf):
        chunks = extractor.extract("any.pdf", "my-doc", "my-report.pdf")
    assert chunks[0].document_id == "my-doc"
    assert chunks[0].document_name == "my-report.pdf"


def test_extract_page_error_skipped_gracefully(extractor):
    """A page that raises during extract_tables must be skipped without crashing."""
    good_table = [["A", "B"], ["1", "2"]]
    error_page = MagicMock()
    error_page.page_number = 1
    error_page.extract_tables = MagicMock(side_effect=RuntimeError("broken page"))
    good_page = MagicMock()
    good_page.page_number = 2
    good_page.extract_tables = MagicMock(return_value=[good_table])

    mock_pdf = MagicMock()
    mock_pdf.pages = [error_page, good_page]
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("pdfplumber.open", return_value=mock_pdf):
        chunks = extractor.extract("any.pdf", "doc-1", "test.pdf")

    assert len(chunks) == 1
    assert chunks[0].page_numbers == [2]


def test_extract_file_open_error_returns_empty(extractor):
    """If pdfplumber.open raises, extract must return [] without crashing."""
    with patch("pdfplumber.open", side_effect=Exception("cannot open file")):
        result = extractor.extract("nonexistent.pdf", "doc-1", "test.pdf")
    assert result == []


def test_extract_pdfplumber_unavailable_returns_empty(extractor):
    """If pdfplumber is not importable, extract must return [] gracefully."""
    with patch.dict(sys.modules, {"pdfplumber": None}):
        result = extractor.extract("any.pdf", "doc-1", "test.pdf")
    assert result == []
