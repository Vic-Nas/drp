# drp ![version](https://img.shields.io/github/v/tag/vicnasdev/drp)

Drop files or paste text, get a link instantly. 
**[Live →](https://drp.vicnas.me)**

```bash
pipx install drp-cli
drp setup && drp up "hello world"
```

## Help

**CLI** → [reference](https://drp.vicnas.me/help/cli/)   
**Expiry** → [how drops expire](https://drp.vicnas.me/help/expiry/)  
**Plans** → [free vs paid](https://drp.vicnas.me/help/plans/)     
**Self-hosting** → [deploy your own](https://drp.vicnas.me/help/privacy/)  

## Deploy

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.com?referralCode=ZIdvo-)

1. Fork → Railway → connect repo → add PostgreSQL
2. Set env vars (see [self-hosting docs](https://drp.vicnas.me/help/privacy/))
3. Start command:
   ```
   python manage.py createcachetable && python manage.py collectstatic --noinput && python manage.py migrate && gunicorn project.wsgi --bind 0.0.0.0:$PORT
   ```
4. Create superuser via Railway shell: `python manage.py createsuperuser`

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate && python manage.py createcachetable
python manage.py runserver
```

## Plans

| | Free | Starter ($3/mo) | Pro ($8/mo) |
|---|---|---|---|
| Max file | 200 MB | 1 GB | 5 GB |
| Storage | — | 5 GB | 20 GB |
| Locked drops | ✗ | ✓ | ✓ |
| Renewable | ✗ | ✓ | ✓ |

## License

Server: source-available, personal/internal use only.    
See [LICENSE](LICENSE).
CLI (`cli/`): MIT.