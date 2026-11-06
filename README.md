# KorokNET

Учебное веб-приложение на FastAPI для регистрации пользователей и подачи заявок на обучение.

## Запуск на macOS

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python -m fastapi dev main.py
```

Откройте <http://127.0.0.1:8000/login>. SQLite-база `db.sqlite3` создаётся при запуске и не хранится в Git.
