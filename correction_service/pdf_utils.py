"""PDF helpers for the Correction Service (no Flask / database dependency).

split_pdf_into_pages and cover_qr_codes_with_gray_squares are used as they
are in process_student_answers.py.
"""
import cv2
import numpy as np
import pymupdf

from process_student_answers import cover_qr_codes_with_gray_squares, split_pdf_into_pages

QUESTIONS = 4
# Each resolution sheet has an instructions page (discarded) followed by one
# page per question: pages 2-5 of the sheet are questions 1-4.
SHEET_PAGES = QUESTIONS + 1


class ScanError(ValueError):
    """The uploaded file cannot be used as a scan of resolution sheets."""


class InvalidPdfError(ScanError):
    """Not a PDF, damaged, encrypted, empty or with a wrong number of pages."""


class QrNotFoundError(ScanError):
    """One or more sheets have no readable QR code."""


def corner_clips(rect):
    """Areas of a page where the QR code is searched, clockwise from the top left."""
    width, height = rect.width * 0.25, rect.height * 0.18
    return [
        pymupdf.Rect(rect.x0, rect.y0, rect.x0 + width, rect.y0 + height),  # top left
        pymupdf.Rect(rect.x1 - width, rect.y0, rect.x1, rect.y0 + height),  # top right
        pymupdf.Rect(rect.x1 - width, rect.y1 - height, rect.x1, rect.y1),  # bottom right
        pymupdf.Rect(rect.x0, rect.y1 - height, rect.x0 + width, rect.y1),  # bottom left
    ]


def read_qr_value(page):
    """Value of the QR code of a page, or None.

    The corners are tried clockwise (top left, top right, bottom right,
    bottom left) and the first QR code that can be decoded wins.
    """
    detector = cv2.QRCodeDetector()
    for clip in corner_clips(page.rect):
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(2, 2),
            clip=clip,
            colorspace=pymupdf.csRGB,
            alpha=False,
        )
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
        value, _, _ = detector.detectAndDecode(cv2.cvtColor(image, cv2.COLOR_RGB2GRAY))
        if value:
            return value
    return None


def read_sheet_qr(sheet_pages):
    """QR value of a sheet: the first one found on its pages (normally the first page)."""
    for page_document in sheet_pages:
        value = read_qr_value(page_document[0])
        if value:
            return value
    return None


def page_png(page_document):
    return page_document[0].get_pixmap(
        matrix=pymupdf.Matrix(2, 2),
        colorspace=pymupdf.csRGB,
        alpha=False,
    ).tobytes("png")


def split_scan(data):
    """Split a scanned PDF into resolution sheets.

    The PDF may hold one or more sheets, one after the other and in order, with
    SHEET_PAGES pages each. Returns a list with one
    (position, qr_value, [png_question_1, ..., png_question_4]) per sheet, where
    position (1-based) is the place of the sheet in the PDF and qr_value the
    text of its QR code. The instructions page is dropped, and the QR codes are
    covered in the PNG images.

    Raises InvalidPdfError if the file is not a usable PDF and QrNotFoundError
    (listing every sheet) if some sheet has no readable QR code.
    """
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise InvalidPdfError("The file is not a readable PDF.")

    pages = []
    try:
        if document.needs_pass or document.is_encrypted:
            raise InvalidPdfError("The PDF is encrypted or password protected.")
        if document.page_count == 0 or document.page_count % SHEET_PAGES:
            raise InvalidPdfError(
                "The PDF has %d page(s); it must be a multiple of %d (one block of %d pages per resolution sheet)."
                % (document.page_count, SHEET_PAGES, SHEET_PAGES)
            )

        pages = split_pdf_into_pages(document)
        sheets, missing = [], []
        for start in range(0, len(pages), SHEET_PAGES):
            position = start // SHEET_PAGES + 1
            sheet_pages = pages[start:start + SHEET_PAGES]
            value = read_sheet_qr(sheet_pages)
            if value is None:
                missing.append(position)
            else:
                sheets.append((position, value, sheet_pages[1:]))
        if missing:
            raise QrNotFoundError(
                "No readable QR code on sheet(s) %s of the PDF (pages %s). Rescan them and upload again; nothing was saved."
                % (
                    ", ".join(str(p) for p in missing),
                    ", ".join("%d-%d" % ((p - 1) * SHEET_PAGES + 1, p * SHEET_PAGES) for p in missing),
                )
            )

        result = []
        for position, value, question_pages in sheets:
            cover_qr_codes_with_gray_squares(question_pages)
            result.append((position, value, [page_png(q) for q in question_pages]))
        return result
    except ScanError:
        raise
    except Exception as e:
        raise InvalidPdfError("The PDF could not be processed (damaged file?): %s" % e)
    finally:
        document.close()
        for page_document in pages:
            page_document.close()
