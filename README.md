# drp

Drop files or paste text, get a link instantly. No account, no friction — just a key.

- `/b/<key>` — file bin (expires after 90 days inactive)
- `/c/<key>` — clipboard (expires after 24h)
- `sync/client.py` — lightweight folder sync client

## Deploy on Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.com?referralCode=ZIdvo-)

1. Fork this repo
2. New project on Railway → Deploy from GitHub repo
3. Add a PostgreSQL plugin
4. Set environment variables:

```
SECRET_KEY=random_large_string
DOMAIN=RAILWAY_PUBLIC_DOMAIN
DB_URL=Postgres.DATABASE_URL
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=
```
5. Start command
```
python manage.py collectstatic --noinput && python manage.py migrate && gunicorn project.wsgi --bind 0.0.0.0:$PORT
```
Note:
You do need to run python manage.py makemigrations locally
the first time.
Done.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in values
python manage.py migrate
python manage.py runserver
```

## Sync client

```bash
cd sync
pip install watchdog requests
python client.py --setup
```

## License

MIT