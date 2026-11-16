import os
import sys

from django.core.management import execute_from_command_line

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vercel_settings" if os.getenv("VERCEL") else "settings")
execute_from_command_line(sys.argv)
