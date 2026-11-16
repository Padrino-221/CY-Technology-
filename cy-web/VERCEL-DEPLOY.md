# Deploy Credit Manager on Vercel

1. Push these changes to GitHub and import the repository in Vercel. Set **Root Directory** to `cy-web` and select **Django** if Vercel asks for a framework. Leave build and output overrides unset. Vercel discovers `manage.py` and the WSGI entry point, then collects static files.
2. Provision PostgreSQL and a **private** S3-compatible bucket. Give the app a credential scoped to listing and reading, writing, and deleting objects in that bucket. Use independent databases and buckets for previews that need to run.
3. Set the following environment variables in Vercel and in the shell used for database setup. Keep values out of source control.

| Variable | Value |
| --- | --- |
| `CY_SECRET_KEY` | A stable random Django secret. Generate it with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`. |
| `DATABASE_URL` | PostgreSQL connection string. A provider's pooled endpoint is suitable for serving requests. |
| `CY_ALLOWED_HOSTS` | Production and custom hostnames, separated by commas. Use hostnames without a scheme or path. Set the stable Vercel production alias here if used. |
| `CY_S3_BUCKET` | Private upload bucket name. |
| `CY_S3_ACCESS_KEY_ID` | Bucket-scoped access key. |
| `CY_S3_SECRET_ACCESS_KEY` | Matching secret key. |
| `CY_S3_ENDPOINT_URL` | HTTPS endpoint supplied by your S3-compatible provider. Omit for AWS S3. |
| `CY_S3_REGION` | Storage provider's region or signing region. |

4. From `cy-web`, install dependencies with `python -m pip install -r requirements.txt`. Run `python manage.py migrate --settings=vercel_settings` before serving traffic, and again for releases that add migrations. Use the direct database endpoint for this command if required by the provider. Migrations are run explicitly so previews do not change production data.
5. For an empty database, run `python manage.py shell --settings=vercel_settings`, then enter the following lines to create an ordinary staff login.

```python
from getpass import getpass
from django.contrib.auth import get_user_model, password_validation
User = get_user_model()
user = User(username=input("Username: ").strip())
user.full_clean(exclude=["password"])
password = getpass("Password: ")
password_validation.validate_password(password, user)
user.set_password(password)
user.save()
```

6. Deploy, then verify sign-in, static assets, private photo uploads, and offline sync over HTTPS using a test record. Keep staff on one stable production hostname because offline pages and pending changes belong to the browser origin.

## Moving existing records

Before cutover, sync pending browser changes on the old origin, stop staff writes, and take a database and media backup. If the client setup uses SQLite, point `CY_DATA_DIR` at a **working copy** of that backup and use the Windows environment to check and migrate it to the same schema. Export the records and users with:

```powershell
python manage.py dumpdata credit auth.user auth.group --settings=client_settings --output cy-transfer.json
```

Import into a newly migrated, empty production database before creating any hosted users:

```powershell
python manage.py loaddata cy-transfer.json --settings=vercel_settings
```

Copy the contents of the backup's `media` directory to the private bucket, preserving the object keys such as `customers/example.jpg` and `laptops/example.jpg`. Remove the temporary fixture after verifying the import. Check record counts, sign-in, and example photos before directing staff to the new URL.

Vercel limits function request and response bodies to 4.5 MB. New photo submissions are capped at 4 MB combined. Resize any legacy photo over 4 MB before copying it to the bucket so it can be served through the authenticated photo view.
