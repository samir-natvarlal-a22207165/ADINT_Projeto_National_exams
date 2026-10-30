"""Small helpers used by the service (every service has an identical copy)."""
import csv
import io

from werkzeug.routing import IntegerConverter

# Largest identifier accepted anywhere (also the XML-RPC integer limit).
MAX_ID = 2**31 - 1


class BoundedIntConverter(IntegerConverter):
    """<int:x> in a URL that does not match (404) above MAX_ID, instead of a 500 in the database."""

    def __init__(self, map, **kwargs):
        kwargs.setdefault("max", MAX_ID)
        super().__init__(map, **kwargs)


def parse_positive_int(raw, label, required=True):
    """Positive integer up to MAX_ID. Empty input gives None when it is not required."""
    raw = (raw or "").strip()
    if not raw:
        if required:
            raise ValueError("%s is required" % label)
        return None
    if not raw.isdecimal() or not 0 < int(raw) <= MAX_ID:
        raise ValueError("%s must be a positive integer up to %d" % (label, MAX_ID))
    return int(raw)


def read_csv_upload(file):
    """csv.DictReader over an uploaded UTF-8 file, with stripped lower-case column names.

    Raises ValueError with a message for the user if there is no file or it is not UTF-8.
    """
    if not file or not file.filename:
        raise ValueError("Choose a CSV file.")
    try:
        text = file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("File must be UTF-8 encoded.")
    reader = csv.DictReader(io.StringIO(text))
    reader.fieldnames = [(f or "").strip().lower() for f in (reader.fieldnames or [])]
    return reader
