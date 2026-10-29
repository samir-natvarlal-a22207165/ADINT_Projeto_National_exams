from pathlib import Path

import cv2
import numpy as np
import pymupdf


def split_pdf_into_pages(
	document: pymupdf.Document,
) -> list[pymupdf.Document]:
	"""Create an independent one-page PDF document for every source page.

	Args:
		document: PDF document whose pages should be separated.

	Returns:
		A list of open PDF documents, each containing one copied page. The
		caller is responsible for closing every returned document.
	"""
	page_documents = []

	for page_number in range(document.page_count):
		page_document = pymupdf.open()
		page_document.insert_pdf(document, from_page=page_number, to_page=page_number)
		page_documents.append(page_document)

	return page_documents


def print_qr_code_values(page_documents: list[pymupdf.Document]) -> None:
	"""Detect and print readable QR code values from separated pages.

	Args:
		page_documents: One-page PDF documents to scan.

	Returns:
		None.

	Prints each decoded value with its one-based page number. QR codes that
	cannot be decoded are ignored.
	"""

	# Use OpenCV's QR code detector to find QR codes in the pages.
	detector = cv2.QRCodeDetector()

	for page_number, page_document in enumerate(page_documents, start=1):
		page = page_document[0]

		# Get a high-resolution pixmap of the page to detect QR codes accurately.
		pixmap = page.get_pixmap(
			matrix=pymupdf.Matrix(2, 2),
			colorspace=pymupdf.csRGB,
			alpha=False,
		)
		# Convert the pixmap to a NumPy array and then to grayscale for QR detection.
		image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
			pixmap.height,
			pixmap.width,
			3,
		)
		# Convert the RGB image to grayscale for QR code detection.
		grayscale = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
		# Detect QR codes and get their decoded values.
		found, values, _, _ = detector.detectAndDecodeMulti(grayscale)

		if found:
			for value in values:
				if value:
					print(f"Page {page_number}: {value}")


def cover_qr_codes_with_gray_squares(
	page_documents: list[pymupdf.Document],
) -> None:
	"""Overlay a gray square on each QR code detected in the pages.

	Args:
		page_documents: One-page PDF documents to scan and modify.

	Returns:
		None. The supplied page documents are modified in place.

	The square is slightly larger than the detected QR code and is drawn
	directly onto each page. Documents with no detected QR codes are unchanged.
	"""
	# Use OpenCV's QR code detector to find QR codes in the pages.
	detector = cv2.QRCodeDetector()
	gray = (0.5, 0.5, 0.5)

	for page_document in page_documents:
		page = page_document[0]
		# Get a high-resolution pixmap of the page to detect QR codes accurately.
		pixmap = page.get_pixmap(
			matrix=pymupdf.Matrix(2, 2),
			colorspace=pymupdf.csRGB,
			alpha=False,
		)
		# Convert the pixmap to a NumPy array and then to grayscale for QR detection.
		image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
			pixmap.height,
			pixmap.width,
			3,
		)
		# Convert the RGB image to grayscale for QR code detection.
		grayscale = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
		# Detect QR codes and get their corner points.
		_, _, points, _ = detector.detectAndDecodeMulti(grayscale)
		if points is None:
			continue

		# Calculate the scaling factors to map pixmap coordinates back to page coordinates.
		scale_x = pixmap.width / page.rect.width
		scale_y = pixmap.height / page.rect.height
		# For each detected QR code, calculate its bounding box and draw a gray square over it.
		for qr_points in points:
			qr_points = qr_points.reshape(-1, 2)
			left, right = qr_points[:, 0].min(), qr_points[:, 0].max()
			top, bottom = qr_points[:, 1].min(), qr_points[:, 1].max()
			side = max(right - left, bottom - top) * 1.1
			center_x = (left + right) / 2
			center_y = (top + bottom) / 2
			page.draw_rect(
				pymupdf.Rect(
					page.rect.x0 + (center_x - side / 2) / scale_x,
					page.rect.y0 + (center_y - side / 2) / scale_y,
					page.rect.x0 + (center_x + side / 2) / scale_x,
					page.rect.y0 + (center_y + side / 2) / scale_y,
				),
				color=None,
				fill=gray,
				overlay=True,
			)


def main():
	"""Split the input PDF, report QR values, and save PDF and PNG pages.

	Opens ``Exam-resolution.pdf`` from the current directory, covers detected
	QR codes in each separated page, and writes numbered PDF and PNG files to
	a sibling ``Exam-resolution-pages`` directory. All opened documents are
	closed before the function returns.

	Returns:
		None.
	"""
	input_path = Path("Exam-resolution.pdf")
	document = pymupdf.open(input_path)
	output_folder = input_path.parent / f"{input_path.stem}-pages"
	output_folder.mkdir(parents=True, exist_ok=True)

	# Split the input PDF into one-page documents, then detect and cover QR codes.
	page_documents = split_pdf_into_pages(document)
	try:
		print_qr_code_values(page_documents)
		cover_qr_codes_with_gray_squares(page_documents)
		# Save each processed page as a matching PDF/PNG pair, then close it.
		for page_number, page_document in enumerate(page_documents, start=1):
			#Saves pages in PDF format
			output_path = output_folder / f"{input_path.stem}-{page_number:03}.pdf"
			page_document.save(output_path)

			#saves pages in PNG format
			png_path = output_folder / f"{input_path.stem}-{page_number:03}.png"
			page_pixmap = page_document[0].get_pixmap(
				matrix=pymupdf.Matrix(2, 2),
				colorspace=pymupdf.csRGB,
				alpha=False,
			)
			page_pixmap.save(png_path)

			#Close the one-page document after saving both formats
			page_document.close()
		print(f"Saved {len(page_documents)} PDFs and PNGs in {output_folder}")
	finally:
		document.close()
		for page_document in page_documents:
			if not page_document.is_closed:
				page_document.close()


if __name__ == "__main__":
	main()
