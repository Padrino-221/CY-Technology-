# CY Technologies Credit Manager

Local Django prototype. Run these PowerShell commands from this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py shell -c "from django.contrib.auth import get_user_model; from getpass import getpass; get_user_model().objects.create_user('frontdesk', password=getpass('Front desk password: '))"
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Open http://127.0.0.1:8000 and sign in. The demo seed is optional and contains fictional records. Every signed-in account can use the front desk screens in this prototype. It uses SQLite and local photo storage. Keep it on loopback with sample records. Shared deployment, role separation, and Access migration are outside this local prototype.
