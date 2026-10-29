from io import BytesIO
from pathlib import Path

import pymupdf
import qrcode


def add_page_titles(document, title: str) -> pymupdf.Document:
	"""Add the same centered title to every page of a PDF document.

	Args:
		document: PDF document whose pages will receive the title.
		title: Text to place near the top of each page.

	Returns:
		The modified PDF document.

	Raises:
		ValueError: If the title does not fit within a page's title area.
	"""
	for page in document:
		margin = min(36, page.rect.width * 0.08)
		title_box = pymupdf.Rect(
			margin,
			18,
			page.rect.width - margin,
			48,
		)
		remaining_space = page.insert_textbox(
			title_box,
			title,
			fontsize=16,
			fontname="helv",
			align=pymupdf.TEXT_ALIGN_CENTER,
		)
		if remaining_space < 0:
			raise ValueError(f"Title does not fit on page {page.number + 1}.")
	return document


def add_qr_code_to_pages(document, value) -> None:
	"""Insert the same QR code into all four corners of every page.

	Args:
		document: PDF document whose pages will receive the QR code.
		value: Non-empty content to encode in the QR code.

	Returns:
		None. The supplied document is modified in place.

	Raises:
		ValueError: If ``value`` is empty or a page is too small for the code.
	"""
	if not value:
		raise ValueError("QR code content must not be empty.")

	qr_image = qrcode.make(value)
	image_data = BytesIO()
	qr_image.save(image_data, format="PNG")
	image_bytes = image_data.getvalue()

	for page in document:
		margin = 18
		size = min(72, page.rect.width - 2 * margin, page.rect.height - 2 * margin)
		if size <= 0:
			raise ValueError(f"Page {page.number + 1} is too small for a QR code.")
		corner_positions = (
			(margin, margin),
			(page.rect.width - margin - size, margin),
			(margin, page.rect.height - margin - size),
			(page.rect.width - margin - size, page.rect.height - margin - size),
		)
		for x, y in corner_positions:
			qr_rect = pymupdf.Rect(x, y, x + size, y + size)
			page.insert_image(qr_rect, stream=image_bytes)


def main():
	"""Add titles and QR codes to the exam template and save the result.

	Reads ``Exam-template.pdf`` from the current directory and writes the
	processed document to ``Exam-template-final.pdf`` in that directory.
	The input document is closed after processing.

	Returns:
		None.
	"""
	input_path = Path("Exam-template.pdf")
	output_path = Path("Exam-template-final.pdf")

	document = pymupdf.open(input_path)

	add_page_titles(document, "YYYYYYYY")
	add_qr_code_to_pages(document, "YYYYYYYY")
	document.save(output_path)
	document.close()


if __name__ == "__main__":
	main()
