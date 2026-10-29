"""PDF helpers for the Correction Service (no Flask / database dependency).

split_pdf_into_pages and cover_qr_codes_with_gray_squares come unchanged from
the teacher-provided process_student_answers.py.
"""
import cv2
import numpy as np
import pymupdf

from process_student_answers import cover_qr_codes_with_gray_squares, split_pdf_into_pages

# Each resolution sheet has 5 pages. Page 1 only holds the exam instructions and
# is discarded; pages 2-5 are questions 1-4.
SHEET_PAGES = 5
QUESTIONS = 4


class ScanError(ValueError):
    """The uploaded file cannot be used as a scan of resolution sheets."""


def page_grayscale(page):
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(2, 2),
        colorspace=pymupdf.csRGB,
        alpha=False,
    )
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
    return pixmap, cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)


def read_qr_values(page_document):
    """Decoded QR code values found in a one-page document."""
    _, grayscale = page_grayscale(page_document[0])
    found, values, _, _ = cv2.QRCodeDetector().detectAndDecodeMulti(grayscale)
    return [v for v in values if v] if found else []


def split_scan(data):
    """Split a scanned PDF into question pages.

    Returns a list of (sheet_number, sheet_id, question_number, single_page_pdf_bytes),
    with sheet_number starting at 1 (order of the sheets in the scan), sheet_id
    read from the QR code of the sheet and question_number in 1..QUESTIONS.
    The instructions page of every sheet is dropped.
    """
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise ScanError("The file is not a readable PDF.")

    pages = split_pdf_into_pages(document)
    try:
        if not pages or len(pages) % SHEET_PAGES:
            raise ScanError(
                "The PDF has %d page(s); it must be a multiple of %d (one block of %d pages per resolution sheet)."
                % (len(pages), SHEET_PAGES, SHEET_PAGES)
            )

        result = []
        for start in range(0, len(pages), SHEET_PAGES):
            sheet_number = start // SHEET_PAGES + 1
            sheet_id = None
            for page_document in pages[start:start + SHEET_PAGES]:
                for value in read_qr_values(page_document):
                    if value.isdigit():
                        sheet_id = int(value)
                        break
                if sheet_id is not None:
                    break
            if sheet_id is None:
                raise ScanError("No readable QR code on sheet %d of the scan." % sheet_number)
            for question in range(1, QUESTIONS + 1):
                result.append((sheet_number, sheet_id, question, pages[start + question].tobytes()))
        return result
    finally:
        document.close()
        for page_document in pages:
            page_document.close()


def render_page_png(page_pdf, zoom=1.5, hide_qr=True):
    """Render a single-page PDF as PNG bytes, optionally covering the QR code."""
    with pymupdf.open(stream=page_pdf, filetype="pdf") as doc:
        if hide_qr:
            cover_qr_codes_with_gray_squares([doc])
        return doc[0].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
