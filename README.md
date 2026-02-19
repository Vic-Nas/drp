# drp

Drop files or paste text, get a link instantly. No account, no friction — just a key.

- `/your-key` — view, copy, download, or replace a drop
- Anonymous text drops expire after **24h** (text) or **90 days** (files)
- Paid accounts get locked drops, longer expiry, and renewable links
- Built-in folder sync client — lightweight OneDrive alternative

## Features

- **Text & file drops** — paste anything or drag a file, get a shareable URL
- **Custom keys** — pick a memorable key or get an auto-generated one
- **Locking** — paid drops are locked to the owner's account; anon drops have a 24h edit window
- **Expiry & renewal** — paid accounts set explicit expiry dates and can renew any time
- **Dashboard** — logged-in users see all drops server-side; anon users get a local browser list with export/import
- **Sync client** — watches a folder and syncs files to drp keys, with auth support
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
python manage.py runserver   # or: make dev
```

Password reset emails print to the terminal in dev — no mail server needed.

## Makefile

```
make dev            # start Django dev server
make test           # run all tests (core + sync)
make migrate        # run migrations
make sync-setup     # install deps & configure sync client
make sync           # start syncing
make sync-login     # (re)authenticate sync client
make sync-status    # show tracked files
```

## Gmail App Password (production email)

Self-service password reset requires an outbound mail account. Gmail works fine:

1. Enable **2-Step Verification** on your Google account
2. Go to **Security → App passwords**, create one named `drp`
3. Copy the 16-character password into `EMAIL_HOST_PASSWORD` in your `.env`

500 emails/day free. For higher volume use [Brevo](https://brevo.com) (3,000/mo free).

## Sync client

```bash
make sync-setup   # installs deps, configures host/folder, optional login
make sync         # start watching
```

Or manually: `python sync/client.py --setup` then `python sync/client.py`.

Watches a local folder and syncs each file to its own drp key. Logged-in users get plan-based expiry and locked drops. On startup, stale keys are detected and re-uploaded.

## Linux service (systemd)

Run drp sync as a background service that starts on boot:

```bash
sudo tee /etc/systemd/system/drp-sync.service > /dev/null <<EOF
[Unit]
Description=drp folder sync
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(which python3) $(pwd)/sync/client.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now drp-sync
```

Check status with `systemctl status drp-sync` and logs with `journalctl -u drp-sync -f`.

Run `make sync-setup` first so the config file exists at `~/.drp_sync.json`.

## Plans

| | Free | Starter ($3/mo) | Pro ($8/mo) |
|---|---|---|---|
| Max file size | 200 MB | 1 GB | 5 GB |
| Max text size | 500 KB | 2 MB | 10 MB |
| Storage | — | 5 GB | 20 GB |
| Expiry | 24h / 90d | Up to 1 year | Up to 3 years |
| Locked drops | ✗ | ✓ | ✓ |
| Renewable | ✗ | ✓ | ✓ |

Upgrade from your account page after signing up — billing is handled via Lemon Squeezy.

## License

MIT