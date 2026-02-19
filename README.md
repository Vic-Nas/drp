# drp

Drop files or paste text, get a link instantly. No account, no friction — just a key.

- `/your-key` — view, copy, download, or replace a drop
- Anonymous text drops expire after **24h**, file drops after **90 days inactive**
- Paid accounts get locked drops, longer expiry, and renewable links
- `sync/client.py` — lightweight folder sync client

## Features

- **Text & file drops** — paste anything or drag a file, get a shareable URL
- **Custom keys** — pick a memorable key or get an auto-generated one
- **Locking** — paid drops are locked to the owner's account; anon drops have a 24h edit window
- **Expiry & renewal** — paid accounts set explicit expiry dates and can renew any time
- **Dashboard** — logged-in users see all drops server-side; anon users get a local browser list with export/import
- **Sync client** — watchdog-based folder sync, one file per key
- **Self-hostable** — deploys to Railway in a few clicks, runs locally with SQLite

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
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST_USER=you@gmail.com
EMAIL_HOST_PASSWORD=xxxx xxxx xxxx xxxx
DEFAULT_FROM_EMAIL=you@gmail.com
ADMIN_EMAIL=you@gmail.com
LEMONSQUEEZY_API_KEY=
LEMONSQUEEZY_SIGNING_SECRET=
LEMONSQUEEZY_STORE_ID=
LEMONSQUEEZY_STARTER_VARIANT_ID=
LEMONSQUEEZY_PRO_VARIANT_ID=
```

5. Start command:

```
python manage.py createcachetable && python manage.py collectstatic --noinput && python manage.py migrate && gunicorn project.wsgi --bind 0.0.0.0:$PORT
```

> Note: run `python manage.py makemigrations` locally the first time before deploying.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in Cloudinary values; leave EMAIL_* blank for console output
python manage.py migrate
python manage.py createcachetable
python manage.py runserver
```

Password reset emails will print to the terminal in local dev — no mail server needed.

## Gmail App Password (production email)

Self-service password reset requires an outbound mail account. Gmail works fine:

1. Enable **2-Step Verification** on your Google account
2. Go to **Security → App passwords**, create one named `drp`
3. Copy the 16-character password into `EMAIL_HOST_PASSWORD` in your `.env`

500 emails/day free. For higher volume use [Brevo](https://brevo.com) (3,000/mo free).

## Sync client

```bash
cd sync
pip install watchdog requests
python client.py --setup
```

Watches a local folder and syncs each file to its own drp key. Edits and deletes propagate automatically.

## Plans

| | Free | Starter ($3/mo) | Pro ($8/mo) |
|---|---|---|---|
| Max file size | 200 MB | 1 GB | 5 GB |
| Max text size | 500 KB | 2 MB | 10 MB |
| Storage | — | 5 GB | 20 GB |
| Expiry | 24h / 90d inactive | Up to 1 year | Up to 3 years |
| Locked drops | ✗ | ✓ | ✓ |
| Renewable | ✗ | ✓ | ✓ |

Upgrade from your account page after signing up — billing is handled via Lemon Squeezy.

## License

MIT