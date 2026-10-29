"""PDF helpers for the Printing Service (no Flask / database dependency).

add_page_titles and add_qr_code_to_pages come unchanged from the
teacher-provided generate_resolution_sheets.py.
"""
import pymupdf

from generate_resolution_sheets import add_page_titles, add_qr_code_to_pages

def title_fits(page_rect, title):
    """True if add_page_titles accepts the title on a blank page of this size."""
    with pymupdf.open() as scratch:
        scratch.new_page(width=page_rect.width, height=page_rect.height)
        try:
            add_page_titles(scratch, title)
        except ValueError:
            return False
    return True


def fit_course(template_path, course, suffix):
    """Course name, cut short with "..." if needed, so that course + suffix fits
    in the title box of add_page_titles (it raises ValueError otherwise)."""
    with pymupdf.open(template_path) as template:
        page_rect = template[0].rect

    short = course
    while not title_fits(page_rect, short + suffix):
        course = course[:-1].rstrip()
        if not course:
            raise ValueError("title does not fit on the page")
        short = course + "..."
    return short


def build_resolution_pdf(template_path, sheets):
    """One PDF with a copy of the template per sheet.

    sheets is a list of (sheet_id, title). The QR code of each copy encodes
    the sheet id.
    """
    result = pymupdf.open()
    try:
        for sheet_id, title in sheets:
            with pymupdf.open(template_path) as copy:
                add_page_titles(copy, title)
                add_qr_code_to_pages(copy, str(sheet_id))
                result.insert_pdf(copy)
        return result.tobytes()
    finally:
        result.close()
