# AP workflow integrations

The app keeps OCR local with Tesseract and PyMuPDF. The following integrations
are optional and are disabled until their environment variables and provider
accounts are configured.

## Approval reminders and mailbox polling

From PowerShell, in the backend folder:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py process_approval_notifications
.\.venv\Scripts\python.exe manage.py poll_invoice_mailbox
```

Apply migrations before starting to use the new integration fields.

Set `AP_IMAP_HOST`, `AP_IMAP_USERNAME`, and `AP_IMAP_PASSWORD`; optionally set
`AP_IMAP_PORT` (default `993`) and `AP_IMAP_MAILBOX` (default `INBOX`). Use an
IMAP app password where the mail provider supports it. The poller uses IMAP over
SSL, checks unread messages, imports supported PDF/image attachments, records
the server's UID validity and UID to prevent duplicate imports, and marks a
message read only after it has been processed. Messages over 25 MB are skipped.
The existing dashboard `.eml` upload remains available.

To register repeat tasks for the signed-in Windows account:

```powershell
.\register_ap_scheduled_tasks.ps1
```

This registers the reminder command hourly and the IMAP poller every five
minutes. Tasks run only while that account is signed in. Run the script again
to update the tasks. Triggers repeat for 10 years; rerun the setup script before
they expire. Output is appended to `backend\logs\`; use Task Scheduler to
inspect run history and failures.

## QuickBooks Online

Install the base backend dependencies (including token encryption):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Configure these user environment variables before starting Django:

- `QUICKBOOKS_CLIENT_ID`
- `QUICKBOOKS_CLIENT_SECRET`
- `QUICKBOOKS_REDIRECT_URI` (must exactly match the Intuit app configuration;
  for local Vite development use
  `http://localhost:5173/api/invoices/integrations/quickbooks/callback/`)
- `INTEGRATION_ENCRYPTION_KEY`
- `QUICKBOOKS_SANDBOX` (`true` for a sandbox company; otherwise production)

Generate a Fernet key locally with:

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep the generated key private and stable; it encrypts the stored OAuth tokens.
An Administrator connects the company from the Payment Processing page.
Configure each active vendor's QuickBooks vendor ID and expense-account ID in
Django admin. A Payment Clerk can then create a pending bill for an approved
invoice. The sync is idempotent per invoice; review the pending bill in
QuickBooks before posting or paying it.

## Stripe Connect supplier transfers

Set `STRIPE_SECRET_KEY` to the intended Stripe platform key. Vendor connected
account IDs are configured in Django admin. A Payment Clerk can initiate a
transfer only for an approved invoice with an open payment request, and the UI
requires explicit confirmation of the vendor and amount. Stripe keys control
test versus live mode. A live key can move real funds; do not configure one
until the Stripe Connect platform, vendor accounts, balances, and payout
process have been verified. A transfer to a connected Stripe account does not
by itself confirm a bank payout.
