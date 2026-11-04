<<<<<<< HEAD
# Templegate Technologies — Level 2 Project

Accounts Payable automation application for vendor onboarding, invoice intake
and OCR review, purchase-order and goods-receipt matching, approvals, and
payment tracking.

## Technology stack

- Frontend: ReactJS 19, Vite
- Backend: Django 6.1, Django REST Framework
- Database: PostgreSQL
- OCR: Tesseract, PyMuPDF, Pillow

## Requirements

- Windows 10/11
- Python 3.13
- Node.js 20.19+ or 22.12+
- PostgreSQL
- Tesseract OCR

The OCR code detects `tesseract.exe` from `PATH`. If it is installed in a
non-standard location, set the `TESSERACT_CMD` environment variable to its full
path.

## Run locally (Windows PowerShell)

### 1. Create the PostgreSQL database

Create a database named `templegate_ap` in pgAdmin, or run this in PowerShell if
the PostgreSQL command-line tools are on `PATH`:

```powershell
createdb -U postgres templegate_ap
```

### 2. Install and start Django

In the first PowerShell terminal:

```powershell
cd C:\path\to\templegate-ap-automation
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$env:DJANGO_DEBUG = "true"
$env:DJANGO_SECRET_KEY = "local-development-only"
$env:DB_NAME = "templegate_ap"
$env:DB_USER = "postgres"
$env:DB_PASSWORD = Read-Host "PostgreSQL password"
$env:DB_HOST = "localhost"
$env:DB_PORT = "5432"

.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Keep this terminal open while using the app. The local secret above is only for
development; never reuse it in a deployed environment.

### 3. Install and start React

In a second PowerShell terminal:

```powershell
cd C:\path\to\templegate-ap-automation
cd frontend
npm ci
npm run dev
```

Open the Vite URL printed in the terminal (usually
`http://localhost:5173`). Vite proxies `/api` requests to Django on port 8000.

### 4. Sign in and test

Register through the app to create an AP Clerk account. New users start with
that role. Assign Approver, Payment Clerk, or Administrator roles to test users
through Django admin at `http://127.0.0.1:8000/admin/`.

The sample workflow is: create and approve a vendor → create a purchase order →
record its goods receipt → upload and review an invoice → link and pass the
three-way match → submit for approval → approve → record payment.

## Run checks

```powershell
cd C:\path\to\templegate-ap-automation
cd backend
$env:DJANGO_DEBUG = "true"
$env:DJANGO_SECRET_KEY = "local-development-only"
$env:DB_NAME = "templegate_ap"
$env:DB_USER = "postgres"
$env:DB_PASSWORD = Read-Host "PostgreSQL password"
$env:DB_HOST = "localhost"
$env:DB_PORT = "5432"
.\.venv\Scripts\python.exe manage.py test invoices

cd ..\frontend
npm run lint
npm run build
```

## Submission details

- **GitHub repository:** https://github.com/anandkatti2024/AP-Automation-System
- **Database schema:** [database_schema.sql](database_schema.sql)
- **Demo video:** Add the video URL when available.
- **Challenges and solutions:** Include the separate challenges-and-solutions
  document with the submission email.
- **Live application: https://ap-automation-system-2.onrender.com/
=======
# AP-Automation-System
>>>>>>> origin/main
