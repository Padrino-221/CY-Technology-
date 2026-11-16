"""Initialize, run, and back up a single-PC installation."""
import argparse
from contextlib import closing
from datetime import datetime
from getpass import getpass
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import webbrowser
from zipfile import ZIP_DEFLATED, ZipFile

os.environ["DJANGO_SETTINGS_MODULE"] = "client_settings"

import django
from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.wsgi import get_wsgi_application
from django.db import transaction
from waitress import create_server
from whitenoise import WhiteNoise

HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def setup():
    call_command("migrate", interactive=False)
    users = get_user_model()
    if users.objects.filter(is_active=True).exists():
        return
    while True:
        username = input("Front desk username: ").strip()
        user = users(username=username)
        try:
            user.full_clean(exclude=["password"])
            if not username:
                raise ValidationError("Enter a username.")
            password = getpass("Password (at least 12 characters): ")
            password_validation.validate_password(password, user)
            if password != getpass("Confirm password: "):
                raise ValidationError("The passwords do not match.")
        except ValidationError as error:
            print(" ".join(error.messages))
            continue
        users.objects.create_user(username, password=password)
        print("Front desk account created.")
        return


def backup(daily=False):
    from credit.models import Customer, LaptopPhoto

    now = datetime.now()
    directory = settings.DATA_DIR / "backups"
    directory.mkdir(exist_ok=True)
    if daily and any(directory.glob(f"CY-{now:%Y-%m-%d}-*.zip")):
        return
    final = directory / f"CY-{now:%Y-%m-%d-%H%M%S-%f}.zip"
    partial = final.with_suffix(".tmp")
    source_path = settings.DATABASES["default"]["NAME"]
    with TemporaryDirectory(dir=directory) as temp:
        snapshot = Path(temp) / "cy.sqlite3"
        try:
            # The immediate transaction blocks record writes while a separate reader takes the snapshot.
            with transaction.atomic():
                with closing(sqlite3.connect(source_path)) as source, closing(sqlite3.connect(snapshot)) as destination:
                    source.backup(destination)
                with ZipFile(partial, "w", ZIP_DEFLATED) as archive:
                    archive.write(snapshot, "cy.sqlite3")
                    photos = set(Customer.objects.exclude(photo="").values_list("photo", flat=True))
                    photos.update(LaptopPhoto.objects.values_list("image", flat=True))
                    root = settings.MEDIA_ROOT.resolve()
                    for name in sorted(photos):
                        photo = (root / name).resolve()
                        if not photo.is_relative_to(root):
                            raise ValueError("Invalid photo path in database.")
                        archive.write(photo, "media/" + photo.relative_to(root).as_posix())
            partial.replace(final)
        finally:
            partial.unlink(missing_ok=True)
    print(f"Backup saved to {final}")


def serve(port, open_browser):
    setup()
    try:
        backup(daily=True)
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"Startup backup failed: {error}. Use Backup.cmd to retry.")
    application = WhiteNoise(get_wsgi_application(), root=settings.BASE_DIR / "static", prefix="/static/")
    server = create_server(application, host=HOST, port=port, max_request_body_size=8 * 1024 * 1024)
    url = f"http://{HOST}:{port}/"
    print(f"CY Credit Manager is running at {url}")
    print("Keep this window open while using the app. Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    server.run()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("setup", "serve", "backup"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    django.setup()
    if args.action == "setup":
        setup()
    elif args.action == "backup":
        if not settings.DATABASES["default"]["NAME"].is_file():
            parser.error("Run Install.cmd before taking a backup.")
        backup()
    else:
        serve(args.port, not args.no_browser)


if __name__ == "__main__":
    main()
