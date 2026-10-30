"""PDF helpers for the Printing Service (no Flask / database dependency).

add_page_titles and add_qr_code_to_pages are used as they are in
generate_resolution_sheets.py.
"""
import pymupdf

from generate_resolution_sheets import add_page_titles, add_qr_code_to_pages

TITLE_FONT = "helv"
TITLE_SIZE = 16  # same as in add_page_titles
QR_SPACE = 100  # width taken by the QR codes in the top corners


def fit_course(course, suffix, page_width):
    """Course name, cut short with "..." if needed, so that course + suffix does
    not run into the QR codes in the top corners of the page."""
    max_width = page_width - 2 * QR_SPACE

    def fits(text):
        return pymupdf.get_text_length(text + suffix, fontname=TITLE_FONT, fontsize=TITLE_SIZE) <= max_width

    short = course
    while not fits(short):
        course = course[:-1].rstrip()
        if not course:
            raise ValueError("title does not fit on the page")
        short = course + "..."
    return short


def build_resolution_pdf(template_path, sheet_ids, course, date):
    """One PDF with a copy of the template per sheet.

    Every page gets the title "<course> - <date> - page <n>" (n counts the
    instructions page as page 1) and a QR code with the sheet id. The titles are
    the same for every sheet of the exam, so only the QR codes differ.
    """
    result = pymupdf.open()
    try:
        for sheet_id in sheet_ids:
            with pymupdf.open(template_path) as copy:
                width = copy[0].rect.width
                for page in copy:
                    suffix = " - %s - page %d" % (date, page.number + 1)
                    title = fit_course(course, suffix, width) + suffix
                    add_page_titles([page], title)
                add_qr_code_to_pages(copy, str(sheet_id))
                result.insert_pdf(copy)
        return result.tobytes()
    finally:
        result.close()
