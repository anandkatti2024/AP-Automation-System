import re
import unicodedata

from .models import Invoice, Vendor


LEGAL_SUFFIX_ALIASES = {
    "corporation": "corp",
    "incorporated": "inc",
    "limited": "ltd",
    "company": "co",
}
GSTIN_PATTERN = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
)


def _normalized_tokens(value):
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[\W_]+", " ", normalized)
    return normalized.split()


def normalize_invoice_number(value):
    return "".join(_normalized_tokens(value))


def normalize_vendor_name(value):
    tokens = _normalized_tokens(value)

    # OCR may repeat the complete company name on adjacent lines.
    while len(tokens) > 1 and len(tokens) % 2 == 0:
        midpoint = len(tokens) // 2
        if tokens[:midpoint] != tokens[midpoint:]:
            break
        tokens = tokens[:midpoint]

    tokens = [
        LEGAL_SUFFIX_ALIASES.get(token, token)
        for token in tokens
    ]
    return "".join(tokens)


def find_vendor_for_invoice(invoice):
    vendors = Vendor.objects.all().only(
        "name",
        "gstin",
        "onboarding_status",
    )

    invoice_gstin_value = invoice.vendor_gst_number.strip().upper()
    invoice_gstin = normalize_invoice_number(invoice_gstin_value)
    if GSTIN_PATTERN.fullmatch(invoice_gstin_value):
        return next(
            (
                vendor
                for vendor in vendors
                if vendor.gstin
                and normalize_invoice_number(vendor.gstin) == invoice_gstin
            ),
            None,
        )

    invoice_vendor_name = normalize_vendor_name(invoice.vendor_name)
    if not invoice_vendor_name:
        return None

    return next(
        (
            vendor
            for vendor in vendors
            if normalize_vendor_name(vendor.name) == invoice_vendor_name
        ),
        None,
    )


def has_duplicate_invoice(invoice):
    invoice_number = normalize_invoice_number(invoice.invoice_number)
    vendor_name = normalize_vendor_name(invoice.vendor_name)

    if not invoice_number or not vendor_name:
        return False

    candidates = Invoice.objects.exclude(pk=invoice.pk).only(
        "invoice_number",
        "vendor_name",
    )

    return any(
        normalize_invoice_number(candidate.invoice_number) == invoice_number
        and normalize_vendor_name(candidate.vendor_name) == vendor_name
        for candidate in candidates
    )
