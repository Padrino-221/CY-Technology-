"""Settings for the hosted deployment."""
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from settings import *  # noqa: F403

DEBUG = False
SECRET_KEY = os.environ["CY_SECRET_KEY"]
DATABASES = {"default": dj_database_url.parse(os.environ["DATABASE_URL"], ssl_require=True)}
if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured("DATABASE_URL must point to PostgreSQL.")
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

ALLOWED_HOSTS = [
    host for host in dict.fromkeys([
        os.getenv("VERCEL_URL"),
        os.getenv("VERCEL_BRANCH_URL"),
        *os.getenv("CY_ALLOWED_HOSTS", "").replace(",", " ").split(),
    ]) if host
]
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
MIDDLEWARE = [*MIDDLEWARE, "django.middleware.clickjacking.XFrameOptionsMiddleware"]  # noqa: F405

STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405
CY_PHOTO_UPLOAD_LIMIT = 4_000_000
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "access_key": os.environ["CY_S3_ACCESS_KEY_ID"],
            "secret_key": os.environ["CY_S3_SECRET_ACCESS_KEY"],
            "bucket_name": os.environ["CY_S3_BUCKET"],
            "endpoint_url": os.getenv("CY_S3_ENDPOINT_URL"),
            "region_name": os.getenv("CY_S3_REGION"),
            "signature_version": "s3v4",
            "addressing_style": "path",
            "default_acl": None,
        },
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
