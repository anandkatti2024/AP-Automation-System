import base64
import json
from datetime import timedelta
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import IntegrationCredential


class IntegrationConfigurationError(Exception):
    pass


class ExternalIntegrationError(Exception):
    pass


def _fernet():
    key = settings.INTEGRATION_ENCRYPTION_KEY
    if not key:
        raise IntegrationConfigurationError(
            "Set INTEGRATION_ENCRYPTION_KEY before connecting QuickBooks."
        )
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise IntegrationConfigurationError(
            "INTEGRATION_ENCRYPTION_KEY must be a valid Fernet key."
        ) from error


def _decrypt_token(value):
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as error:
        raise IntegrationConfigurationError(
            "QuickBooks tokens cannot be decrypted; verify the encryption key is unchanged."
        ) from error


def _require_quickbooks_settings():
    if not (
        settings.QUICKBOOKS_CLIENT_ID
        and settings.QUICKBOOKS_CLIENT_SECRET
        and settings.QUICKBOOKS_REDIRECT_URI
    ):
        raise IntegrationConfigurationError(
            "Configure the QuickBooks client ID, client secret, and redirect URI."
        )


def _post_form(url, form, headers=None, timeout=30):
    request_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    if headers:
        request_headers.update(headers)
    request = Request(
        url,
        data=urlencode(form).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise ExternalIntegrationError(
            f"External service rejected the request (HTTP {error.code})."
        ) from error
    except (URLError, TimeoutError) as error:
        raise ExternalIntegrationError(
            "Could not connect to the external service."
        ) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExternalIntegrationError(
            "The external service returned an invalid response."
        ) from error


def _quickbooks_token_url():
    return "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"


def quickbooks_authorization_url(state):
    _require_quickbooks_settings()
    base_url = "https://appcenter.intuit.com/connect/oauth2"
    query = urlencode({
        "client_id": settings.QUICKBOOKS_CLIENT_ID,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting",
        "redirect_uri": settings.QUICKBOOKS_REDIRECT_URI,
        "state": state,
    })
    return f"{base_url}?{query}"


def _quickbooks_basic_auth():
    credentials = (
        f"{settings.QUICKBOOKS_CLIENT_ID}:"
        f"{settings.QUICKBOOKS_CLIENT_SECRET}"
    )
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def save_quickbooks_tokens(token_data, realm_id):
    if not isinstance(token_data, dict):
        raise ExternalIntegrationError(
            "QuickBooks returned an invalid OAuth token response."
        )
    if not token_data.get("access_token") or not token_data.get("refresh_token"):
        raise ExternalIntegrationError(
            "QuickBooks did not return both required OAuth tokens."
        )
    encrypt = _fernet().encrypt
    expires_in = int(token_data.get("expires_in", 3600))
    IntegrationCredential.objects.update_or_create(
        provider="QUICKBOOKS",
        defaults={
            "access_token_encrypted": encrypt(
                token_data["access_token"].encode("utf-8")
            ).decode("ascii"),
            "refresh_token_encrypted": encrypt(
                token_data["refresh_token"].encode("utf-8")
            ).decode("ascii"),
            "realm_id": realm_id,
            "expires_at": timezone.now() + timedelta(seconds=expires_in),
        },
    )


def exchange_quickbooks_code(code, realm_id):
    _require_quickbooks_settings()
    token_data = _post_form(
        _quickbooks_token_url(),
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.QUICKBOOKS_REDIRECT_URI,
        },
        headers=_quickbooks_basic_auth(),
    )
    save_quickbooks_tokens(token_data, realm_id)


def _quickbooks_credential():
    _require_quickbooks_settings()
    with transaction.atomic():
        try:
            credential = IntegrationCredential.objects.select_for_update().get(
                provider="QUICKBOOKS"
            )
        except IntegrationCredential.DoesNotExist as error:
            raise IntegrationConfigurationError(
                "Connect QuickBooks from the integration authorization page first."
            ) from error

        if credential.expires_at <= timezone.now() + timedelta(minutes=2):
            refresh_token = _decrypt_token(credential.refresh_token_encrypted)
            token_data = _post_form(
                _quickbooks_token_url(),
                {"grant_type": "refresh_token", "refresh_token": refresh_token},
                headers=_quickbooks_basic_auth(),
            )
            save_quickbooks_tokens(token_data, credential.realm_id)
            credential.refresh_from_db()

        access_token = _decrypt_token(credential.access_token_encrypted)
    return credential, access_token


def create_quickbooks_draft_bill(invoice, vendor):
    if not vendor.quickbooks_vendor_id or not vendor.quickbooks_expense_account_id:
        raise IntegrationConfigurationError(
            "Add this vendor's QuickBooks vendor and expense-account IDs in Django admin."
        )
    credential, access_token = _quickbooks_credential()
    lines = []
    for item in invoice.line_items.all():
        lines.append({
            "Amount": float(item.line_total),
            "DetailType": "AccountBasedExpenseLineDetail",
            "Description": item.description[:4000],
            "AccountBasedExpenseLineDetail": {
                "AccountRef": {"value": vendor.quickbooks_expense_account_id}
            },
        })

    item_total = sum(
        (item.line_total for item in invoice.line_items.all()),
        Decimal("0.00"),
    )
    if not lines or item_total != invoice.total_amount:
        adjustment = invoice.total_amount - item_total
        if adjustment < 0:
            raise IntegrationConfigurationError(
                "Invoice line items exceed the invoice total; correct them before syncing."
            )
        lines.append({
            "Amount": float(adjustment if lines else invoice.total_amount),
            "DetailType": "AccountBasedExpenseLineDetail",
            "Description": (
                "Invoice tax and other charges"
                if lines
                else f"Invoice {invoice.invoice_number}"
            ),
            "AccountBasedExpenseLineDetail": {
                "AccountRef": {"value": vendor.quickbooks_expense_account_id}
            },
        })

    bill = {
        "VendorRef": {"value": vendor.quickbooks_vendor_id},
        "DocNumber": invoice.invoice_number[:21],
        "PrivateNote": (
            f"Imported from Templegate AP; invoice ID {invoice.pk}. "
            "Review this pending bill before posting or paying."
        ),
        "Line": lines,
        "TxnStatus": "Pending",
        "CurrencyRef": {"value": invoice.currency},
    }
    if invoice.invoice_date:
        bill["TxnDate"] = invoice.invoice_date.isoformat()
    if invoice.due_date:
        bill["DueDate"] = invoice.due_date.isoformat()

    base_url = (
        "https://sandbox-quickbooks.api.intuit.com"
        if settings.QUICKBOOKS_SANDBOX
        else "https://quickbooks.api.intuit.com"
    )
    request_id = f"templegate-invoice-{invoice.pk}"
    url = (
        f"{base_url}/v3/company/{credential.realm_id}/bill"
        f"?minorversion=75&requestid={request_id}"
    )
    request = Request(
        url,
        data=json.dumps(bill).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise ExternalIntegrationError(
            f"QuickBooks rejected the bill (HTTP {error.code})."
        ) from error
    except (URLError, TimeoutError) as error:
        raise ExternalIntegrationError(
            "Could not connect to QuickBooks."
        ) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExternalIntegrationError(
            "QuickBooks returned an invalid bill response."
        ) from error

    bill_data = result.get("Bill", {}) if isinstance(result, dict) else {}
    if not isinstance(bill_data, dict) or not bill_data.get("Id"):
        raise ExternalIntegrationError(
            "QuickBooks did not confirm creation of a bill."
        )
    return bill_data["Id"]


def create_stripe_connect_transfer(invoice, vendor, payment_request):
    if not settings.STRIPE_SECRET_KEY:
        raise IntegrationConfigurationError(
            "Configure STRIPE_SECRET_KEY before initiating a Stripe transfer."
        )
    if not vendor.stripe_connected_account_id:
        raise IntegrationConfigurationError(
            "Add the vendor's Stripe connected-account ID in Django admin."
        )

    amount = Decimal(payment_request.requested_amount)
    currency = invoice.currency.lower()
    zero_decimal_currencies = {
        "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg",
        "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
    }
    three_decimal_currencies = {"bhd", "jod", "kwd", "omr", "tnd"}
    if currency in zero_decimal_currencies:
        multiplier = Decimal("1")
    elif currency in three_decimal_currencies:
        multiplier = Decimal("1000")
    else:
        multiplier = Decimal("100")
    minor_units = amount * multiplier
    if minor_units != minor_units.to_integral_value():
        raise IntegrationConfigurationError(
            "The payment amount has precision unsupported by this currency."
        )

    values = {
        "amount": str(int(minor_units)),
        "currency": currency,
        "destination": vendor.stripe_connected_account_id,
        "description": f"AP invoice {invoice.invoice_number}"[:500],
        "transfer_group": f"APINVOICE-{invoice.pk}",
        "metadata[invoice_id]": str(invoice.pk),
        "metadata[invoice_number]": invoice.invoice_number[:100],
        "metadata[payment_request_id]": str(payment_request.pk),
    }
    request = Request(
        f"{settings.STRIPE_API_BASE_URL}/transfers",
        data=urlencode(values).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Idempotency-Key": f"ap-payment-request-{payment_request.pk}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise ExternalIntegrationError(
            f"Stripe rejected the transfer (HTTP {error.code})."
        ) from error
    except (URLError, TimeoutError) as error:
        raise ExternalIntegrationError(
            "Could not connect to Stripe."
        ) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExternalIntegrationError(
            "Stripe returned an invalid transfer response."
        ) from error
    if not isinstance(result, dict) or not result.get("id"):
        raise ExternalIntegrationError(
            "Stripe did not confirm creation of a transfer."
        )
    return result["id"]
