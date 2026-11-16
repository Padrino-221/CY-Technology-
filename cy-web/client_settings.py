"""Production settings for a Windows PC serving its own browser."""
import os
import secrets
from pathlib import Path

from settings import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
DATA_DIR = Path(os.environ.get("CY_DATA_DIR") or Path(os.environ["LOCALAPPDATA"]) / "CY Credit Manager")
DATA_DIR.mkdir(parents=True, exist_ok=True)
secret_path = DATA_DIR / "secret.key"
try:
    with secret_path.open("x", encoding="ascii") as secret:
        secret.write(secrets.token_urlsafe(64))
except FileExistsError:
    pass
SECRET_KEY = secret_path.read_text(encoding="ascii").strip()

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "cy.sqlite3",
        "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 15},
    }
}
MEDIA_ROOT = DATA_DIR / "media"
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
MIDDLEWARE = [*MIDDLEWARE, "django.middleware.clickjacking.XFrameOptionsMiddleware"]  # noqa: F405
