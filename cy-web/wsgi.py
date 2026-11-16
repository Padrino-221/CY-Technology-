import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vercel_settings" if os.getenv("VERCEL") else "settings")
application = get_wsgi_application()
