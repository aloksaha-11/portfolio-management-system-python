# Portfolio Rebalancing System: Python version

This is a Python (Flask) rewrite of the Java Spring application in
`D:\Users\Admin\portfolio-management-system`. It has the same features:

* Sign up, login, logout and password reset by email
* Portfolios, holdings, partial and full sales (SOLD list)
* BSE end-of-day prices, imported automatically from the BSE Bhav Copy
* Create your own plan (rule-based investment suggestions, saved per user)

The web pages (`portfolio_app/static`) are the same HTML, CSS and JavaScript as in the
Java version. The `/api/...` endpoints have the same URLs, request and response
formats, so the pages work without changes.

## Requirements

* Python 3.12 or newer from https://www.python.org/downloads/
  (tick **"Add python.exe to PATH"** during installation)
* The existing MySQL 8 database `portfolio_management_system`. No database changes
  are needed; `db/` contains the same SQL scripts as the Java project.

## Set up (once)

Open PowerShell in this folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configuration

The same environment variables as the Java version:

| Variable | Required | Meaning |
|---|---|---|
| `PORTFOLIO_DB_URL` | yes | e.g. `jdbc:mysql://localhost:3306/portfolio_management_system` (the JDBC form is accepted) |
| `PORTFOLIO_DB_USERNAME` | yes | MySQL user |
| `PORTFOLIO_DB_PASSWORD` | yes | MySQL password |
| `PORTFOLIO_THROTTLE_HMAC_KEY` | yes | Secret of at least 32 characters (login rate limiting) |
| `PORTFOLIO_SESSION_SECRET` | no | Secret of at least 32 characters for the login cookie. Derived from the throttle key when not set |
| `PORTFOLIO_MAIL_HOST`, `PORTFOLIO_MAIL_PORT`, `PORTFOLIO_MAIL_USERNAME`, `PORTFOLIO_MAIL_PASSWORD`, `PORTFOLIO_MAIL_FROM`, `PORTFOLIO_MAIL_STARTTLS`, `PORTFOLIO_MAIL_SSL`, `PORTFOLIO_PUBLIC_BASE_URL` | no | Password-reset emails, as in the Java version |
| `APP_ENV` | no | `production` makes cookies HTTPS-only |
| `PORTFOLIO_HOST` / `PORTFOLIO_PORT` | no | Where to listen. Default `127.0.0.1` and `8000` |
| `PORTFOLIO_SCHEDULER_ENABLED` | no | `false` turns off the automatic BSE import |

## Run

```powershell
.\.venv\Scripts\Activate.ps1
python run.py
```

Open http://localhost:8000/ in a browser. Existing users can log in with their
current passwords (the same Argon2 password hashing as the Java version).

The BSE import runs at 6:15 PM and 7:15 PM IST, Monday to Friday, and once 15 seconds
after start-up. If the Java version is running at the same time against the same
database, both will import the same file. That is harmless (rows are updated, not
duplicated), but you can set `PORTFOLIO_SCHEDULER_ENABLED=false` on one of them.

## Tests

```powershell
python -m pytest
```

## Project layout

```
run.py                        starts the web server (waitress) and the scheduler
portfolio_app/
  __init__.py                 creates the Flask app: pages, security, errors
  config.py                   environment variables
  db.py                       MySQL connections and transactions
  security.py                 passwords, login session, CSRF
  repositories.py             all SQL queries
  jsonutil.py                 JSON request/response helpers
  scheduler.py                BSE import schedule
  api/                        HTTP endpoints (/api/...)
  services/                   business rules (accounts, portfolios, holdings, plans, BSE import, email)
  static/                     web pages, CSS and JavaScript (same as the Java version)
db/                           SQL scripts (same as the Java version)
tests/                        tests for the business rules
```

## Java and Python file mapping

| Java | Python |
|---|---|
| `api/AuthController` | `api/auth.py` |
| `api/PortfolioController`, `api/HoldingController` | `api/portfolios.py` |
| `api/BseMarketDataController` | `api/market_data.py` |
| `api/InvestmentPlanController` | `api/plans.py` |
| `common/ApiInfoController` | `api/__init__.py` |
| `application/UserAccountService`, `LoginService`, `PasswordResetService` | `services/accounts.py` |
| `application/PasswordResetMailService`, `MailSettings` | `services/mail.py`, `config.py` |
| `application/PortfolioService` | `services/portfolios.py` |
| `application/HoldingService` | `services/holdings.py` |
| `application/InvestmentPlanService` | `services/plans.py` |
| `application/BseBhavcopyImporter` | `services/bse_importer.py`, `scheduler.py` |
| `repo/*`, `persistence/*` | `repositories.py` |
| `config/SecurityConfig`, `security/CredentialVersionFilter` | `security.py`, `__init__.py` |
| `config/DatabaseConfig` | `db.py` |
