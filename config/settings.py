import os
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# In production, set SECRET_KEY through an environment variable.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me-before-real-use")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
# Open by default for use on an office LAN. If you expose it to the internet, list your IP or domain here.
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "billing.middleware.DailyBackupMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# Uploaded files (firm logo and signature). They are shown through the app (login needed), not as public files.
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "invoice_new"
LOGOUT_REDIRECT_URL = "login"

# ---- Billing settings ----
# GST rates shown in the dropdown. Confirm them with your accountant before changing.
# Units offered in the billing screen's Unit drop-down (a unit from a pasted row or a product is added automatically).
UNITS = [
    "Nos", "Pcs", "Unit", "Set", "Pair", "Dozen", "Box", "Carton", "Pkt", "Pack", "Bag", "Bundle", "Roll", "Bottle", "Can",
    "Kg", "Gm", "Ton", "Qtl", "Ltr", "Ml", "Mtr", "Cm", "Ft", "Inch", "Sqft", "Sqm", "Hrs", "Job",
]
GST_RATES = [Decimal(x) for x in ("0", "3", "5", "12", "18", "28", "40")]
DEFAULT_GST_RATE = Decimal("18")

# ---- Backups ----
# The database is copied once a day (on the first request) to BACKUP_DIR and the newest BACKUP_KEEP copies are kept.
# Keep this folder on another disk or a synced folder if you can. Superusers can also download a backup from the app.
BACKUP_ENABLED = True
BACKUP_DIR = Path(os.environ.get("BILLING_BACKUP_DIR", BASE_DIR / "backups"))
BACKUP_KEEP = 30
