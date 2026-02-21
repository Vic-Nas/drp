# drp integration tests

Real end-to-end tests against a live drp server and B2 bucket.
**Not run by CI** — run manually.

## Setup

No new env vars. The tests read your existing `.env` and prompt for
email + password once at startup (credentials live in the DB, not the env).

## Running

```bash
pytest integration_tests/ -v
# → drp integration tests → https://drp.vicnas.me
# → Test account email: you@example.com
# → Test account password:
```

```bash
pytest integration_tests/cli/ -v    # CLI layer only
pytest integration_tests/core/ -v   # API layer only
pytest integration_tests/ -v -x     # stop on first failure
```

## Safety

- All test keys are prefixed `drptest-` and deleted at session end, even on failure.
- Uses an isolated `/tmp/drp-integration-*/` config dir — `~/.config/drp/` is never touched.
- Safe against production DB: only the test account's own drops are created/deleted.

## Layout

```
integration_tests/
  conftest.py                 fixtures: env, session, isolated config, key tracking
  cli/
    test_upload_download.py   drp up / drp get
    test_manage.py            drp rm / mv / cp / renew
    test_browse.py            drp ls / status / ping / diff / edit
    test_account.py           drp save / load / login / logout
    test_serve.py             drp serve
    test_parser.py            drp -h / --help / -V / no args
  core/
    test_api_auth.py          get_csrf / login
    test_api_text.py          upload_text / get_clipboard
    test_api_file.py          upload_file / get_file
    test_api_actions.py       delete / rename / renew / save_bookmark / list_drops / key_exists
```
