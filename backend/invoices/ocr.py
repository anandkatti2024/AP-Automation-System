
import re
import os
import shutil
from io import BytesIO
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytesseract
import pymupdf
from PIL import Image, ImageSequence


configured_tesseract = os.environ.get("TESSERACT_CMD")
if configured_tesseract:
    pytesseract.pytesseract.tesseract_cmd = configured_tesseract
else:
    tesseract_executable = shutil.which("tesseract")
    if tesseract_executable:
        pytesseract.pytesseract.tesseract_cmd = tesseract_executable
    else:
        windows_tesseract = Path(
            r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        )
        if windows_tesseract.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(windows_tesseract)


def process_image(image):
    """Extract text from an image and calculate OCR confidence."""
    image = image.convert("RGB")

    text = pytesseract.image_to_string(
        image,
        lang="eng",
    )

    data = pytesseract.image_to_data(
        image,
        output_type=pytesseract.Output.DICT,
        lang="eng",
    )

    scores = []

    for word, confidence in zip(data["text"], data["conf"]):
        try:
            score = float(confidence)

            if word.strip() and score >= 0:
                scores.append(score)

        except (ValueError, TypeError):
            continue

    confidence = (
        round(sum(scores) / len(scores), 2)
        if scores
        else None
    )

    return text, confidence


def extract_text_from_file(uploaded_file):
    """Extract text from PDF, PNG, JPG, JPEG, and TIFF files."""
    file_bytes = uploaded_file.read()
    filename = uploaded_file.name.lower()
    results = []

    try:
        if filename.endswith(".pdf"):
            with pymupdf.open(
                stream=file_bytes,
                filetype="pdf",
            ) as pdf:
                for page in pdf:
                    pix = page.get_pixmap(
                        matrix=pymupdf.Matrix(2, 2)
                    )

                    image = Image.open(
                        BytesIO(pix.tobytes("png"))
                    )

                    text, _ = process_image(image)
                    results.append(text)

        else:
            image = Image.open(BytesIO(file_bytes))

            for frame in ImageSequence.Iterator(image):
                text, _ = process_image(frame)
                results.append(text)

        return "\n".join(results).strip()

    finally:
        uploaded_file.seek(0)


def calculate_file_confidence(uploaded_file):
    """Calculate average OCR confidence across all pages or frames."""
    file_bytes = uploaded_file.read()
    filename = uploaded_file.name.lower()
    scores = []

    try:
        if filename.endswith(".pdf"):
            with pymupdf.open(
                stream=file_bytes,
                filetype="pdf",
            ) as pdf:
                for page in pdf:
                    pix = page.get_pixmap(
                        matrix=pymupdf.Matrix(2, 2)
                    )

                    image = Image.open(
                        BytesIO(pix.tobytes("png"))
                    )

                    _, confidence = process_image(image)

                    if confidence is not None:
                        scores.append(confidence)

        else:
            image = Image.open(BytesIO(file_bytes))

            for frame in ImageSequence.Iterator(image):
                _, confidence = process_image(frame)

                if confidence is not None:
                    scores.append(confidence)

        return (
            round(sum(scores) / len(scores), 2)
            if scores
            else None
        )

    finally:
        uploaded_file.seek(0)


def extract_vendor_name(text):
    """
    Extract the vendor name from OCR text.

    Searches line by line to avoid combining text across lines
    or extracting a company name from an email address.
    """
    lines = text.splitlines()

    # First, look for company names with recognizable legal suffixes.
    company_pattern = re.compile(
        r"\b("
        r"[A-Z][A-Za-z0-9&.'-]*"
        r"(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,5}"
        r"\s+"
        r"(?:Corporation|Corp\.?|Limited|Ltd\.?|Inc\.?|LLC)"
        r")\b",
        re.IGNORECASE,
    )

    for line in lines:
        cleaned = line.replace("\\", " ").replace("|", " ").strip()

        # Ignore contact details and invoice section headings.
        if (
            "@" in cleaned
            or re.search(
                r"\b(email|phone|telephone|gst|invoice|"
                r"bill\s+to|ship\s+to|subtotal|total)\b",
                cleaned,
                re.IGNORECASE,
            )
        ):
            continue

        match = company_pattern.search(cleaned)

        if match:
            return match.group(1).strip(" .,:-")

    # Fallback: inspect the first few meaningful header lines.
    excluded_lines = {
        "INVOICE",
        "TAX INVOICE",
        "BILL",
        "BILL TO",
        "SHIP TO",
        "PURCHASE ORDER",
    }

    for line in lines[:12]:
        cleaned = line.replace("\\", " ").replace("|", " ").strip()
        cleaned = re.sub(r"\s+", " ", cleaned)

        if not cleaned:
            continue

        if "@" in cleaned:
            continue

        if re.search(
            r"\b(email|phone|telephone|gst|invoice|"
            r"date|address|subtotal|total)\b",
            cleaned,
            re.IGNORECASE,
        ):
            continue

        if cleaned.upper() in excluded_lines:
            continue

        # Ignore lines containing mostly numbers or symbols.
        if not re.search(r"[A-Za-z]{3,}", cleaned):
            continue

        # Avoid selecting long address-like or sentence-like lines.
        if len(cleaned) > 60:
            continue

        return cleaned.strip(" .,:-")

    return None


def extract_invoice_fields(text):
    """Extract common invoice fields from OCR text."""
    fields = {}

    # Invoice number.
    match = re.search(
        r"\bInvoice\s*(?:No\.?|Number|#)\s*[:=]*\s*"
        r"[_~\s-]*([A-Z0-9][A-Z0-9/-]*)",
        text,
        re.IGNORECASE,
    )

    if match:
        fields["invoice_number"] = match.group(1).strip()

    # Vendor name.
    vendor_name = extract_vendor_name(text)

    if vendor_name:
        fields["vendor_name"] = vendor_name

    # Vendor GST number.
    match = re.search(
        r"\bGST\s*(?:No\.?|Number|IN)?\s*[:#]?\s*"
        r"([A-Z0-9]{8,20})",
        text,
        re.IGNORECASE,
    )

    if match:
        fields["vendor_gst_number"] = match.group(1).strip()

    # Date parsing.
    date_pattern = (
        r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
        r"|\d{4}-\d{2}-\d{2}"
        r"|\d{1,2}[/-]\d{1,2}[/-]\d{4})"
    )

    def parse_date(value):
        formats = (
            "%d %b %Y",
            "%d %B %Y",
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%m/%d/%Y",
            "%m-%d-%Y",
        )

        for fmt in formats:
            try:
                return datetime.strptime(
                    value.strip(),
                    fmt,
                ).date()
            except ValueError:
                continue

        return None

    # Invoice date: match a Date label but not Due Date.
    match = re.search(
        r"(?<!Due )\bDate\s*[:=]\s*" + date_pattern,
        text,
        re.IGNORECASE,
    )

    if match:
        parsed = parse_date(match.group(1))

        if parsed:
            fields["invoice_date"] = parsed

    # Due date.
    match = re.search(
        r"\bDue\s+Date\s*[:=]\s*" + date_pattern,
        text,
        re.IGNORECASE,
    )

    if match:
        parsed = parse_date(match.group(1))

        if parsed:
            fields["due_date"] = parsed

    # Normalize spaces introduced by OCR around punctuation.
    normalized = re.sub(
        r"(?<=\d)\s+([,.])",
        r"\1",
        text,
    )

    def find_amount(pattern):
        match = re.search(
            pattern,
            normalized,
            re.IGNORECASE,
        )

        if not match:
            return None

        value = match.group(1)
        value = value.replace(",", "").replace(" ", "")

        try:
            return Decimal(value)
        except Exception:
            return None

    # Subtotal.
    subtotal = find_amount(
        r"\bSubtotal\b\s*:?\s*(?:INR|Rs\.?|₹|\$)?\s*"
        r"([0-9][0-9,\s]*\.\d{2})"
    )

    # Tax / GST.
    tax = find_amount(
        r"\b(?:Tax|GST)\b(?:\s*\([^)]*\))?\s*:?\s*"
        r"(?:INR|Rs\.?|₹|\$)?\s*"
        r"([0-9][0-9,\s]*\.\d{2})"
    )

    # Total amount. Prefer "Total Amount Due" or "Total" labels.
    total = find_amount(
        r"\bTotal(?:\s+Amount\s+Due)?\b\s*:?\s*"
        r"(?:INR|Rs\.?|₹|\$)?\s*"
        r"([0-9][0-9,\s]*\.\d{2})"
    )

    if subtotal is not None:
        fields["subtotal"] = subtotal

    if tax is not None:
        fields["tax_amount"] = tax

    if total is not None:
        fields["total_amount"] = total

    return fields


def extract_line_items(text):
    """Extract simple description, quantity, unit-price, and total rows."""
    header_pattern = re.compile(
        r"\b(?:description|item|material|product)\b.*"
        r"\b(?:qty|quantity)\b.*"
        r"\b(?:unit\s+price|rate|price)\b.*"
        r"\b(?:total|amount)\b",
        re.IGNORECASE,
    )
    row_pattern = re.compile(
        r"^\s*(?:(?P<line_number>\d+)[.)]?\s+)?"
        r"(?P<description>.+?)\s+"
        r"(?P<quantity>\d+(?:\.\d+)?)\s+"
        r"(?:INR|Rs\.?|₹|\$|€|£)?\s*"
        r"(?P<unit_price>-?\d[\d,]*(?:\.\d{1,2})?)\s+"
        r"(?:INR|Rs\.?|₹|\$|€|£)?\s*"
        r"(?P<line_total>-?\d[\d,]*(?:\.\d{1,2})?)\s*$",
        re.IGNORECASE,
    )
    end_pattern = re.compile(
        r"^\s*(subtotal|tax|gst|total|amount\s+due|terms|"
        r"bank|payment|grand\s+total)\b",
        re.IGNORECASE,
    )

    def parse_decimal(value):
        return Decimal(value.replace(",", ""))

    items = []
    reading_table = False

    for line in text.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if not cleaned:
            continue

        if not reading_table:
            if header_pattern.search(cleaned):
                reading_table = True
            continue

        if end_pattern.search(cleaned):
            reading_table = False
            continue

        match = row_pattern.fullmatch(cleaned)
        if not match:
            continue

        description = match.group("description").strip(" .|")
        if not description or not re.search(r"[A-Za-z]", description):
            continue

        try:
            items.append({
                "line_number": (
                    int(match.group("line_number"))
                    if match.group("line_number")
                    else len(items) + 1
                ),
                "description": description,
                "quantity": parse_decimal(match.group("quantity")),
                "unit_price": parse_decimal(match.group("unit_price")),
                "line_total": parse_decimal(match.group("line_total")),
            })
        except (ValueError, ArithmeticError):
            continue

    return items
