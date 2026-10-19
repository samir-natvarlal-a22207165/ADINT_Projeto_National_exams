"""PDF helpers for the Correction Service (no Flask / database dependency)."""
import io

from pypdf import PdfReader, PdfWriter

# Each resolution sheet has 5 pages. Page 1 only holds the exam instructions and
# is discarded; pages 2-5 are questions 1-4.
SHEET_PAGES = 5
QUESTIONS = 4

# Area covered with a black box before a page is shown to a professor, as
# fractions of the page: (left, top, right, bottom).
# ASSUMPTION: QR code in the top-right corner. Adjust to match the layout
# produced by generate_resolution_sheets.py.
QR_REGION = (0.70, 0.00, 1.00, 0.20)


class ScanError(ValueError):
    """The uploaded file cannot be used as a scan of resolution sheets."""


def split_scan(data):
    """Split a scanned PDF into question pages.

    Returns a list of (sheet_number, question_number, single_page_pdf_bytes),
    with sheet_number starting at 1 (order of the sheets in the scan) and
    question_number in 1..QUESTIONS. The instructions page of every sheet is
    dropped.
    """
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = list(reader.pages)
    except Exception:
        raise ScanError("The file is not a readable PDF.")

    if not pages or len(pages) % SHEET_PAGES:
        raise ScanError(
            "The PDF has %d page(s); it must be a multiple of %d (one block of %d pages per resolution sheet)."
            % (len(pages), SHEET_PAGES, SHEET_PAGES)
        )

    result = []
    for index, page in enumerate(pages):
        position = index % SHEET_PAGES  # 0 = instructions page
        if position == 0:
            continue
        writer = PdfWriter()
        writer.add_page(page)
        buffer = io.BytesIO()
        writer.write(buffer)
        result.append((index // SHEET_PAGES + 1, position, buffer.getvalue()))
    return result


def render_page_png(page_pdf, zoom=1.5, hide_qr=True):
    """Render a single-page PDF as PNG bytes, optionally blacking out the QR code.

    Needs PyMuPDF (pip install pymupdf), imported lazily so the rest of the
    service works without it.
    """
    import fitz  # PyMuPDF

    with fitz.open(stream=page_pdf, filetype="pdf") as doc:
        page = doc[0]
        if hide_qr:
            rect = page.rect
            left, top, right, bottom = QR_REGION
            box = fitz.Rect(
                rect.x0 + left * rect.width,
                rect.y0 + top * rect.height,
                rect.x0 + right * rect.width,
                rect.y0 + bottom * rect.height,
            )
            page.draw_rect(box, color=None, fill=(0, 0, 0), overlay=True)
        return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")
