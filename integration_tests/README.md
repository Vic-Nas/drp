# drp integration tests

Real end-to-end tests that talk to an actual drp server and B2 bucket.
**Not run by CI** — run manually when you want full coverage against a live environment.

## Setup

```
cp .env.example .env          # or copy your existing deploy .env
pip install pytest python-dotenv requests
```

Required `.env` keys (same as the server):

```
DRP_TEST_HOST=https://drp.vicnas.me   # or http://localhost:8000
DRP_TEST_EMAIL=test@example.com
DRP_TEST_PASSWORD=yourpassword
```

`DRP_TEST_HOST` defaults to `https://drp.vicnas.me` if omitted.
The test account must exist on that host.

## Running

```bash
# All integration tests
pytest integration_tests/ -v

# Just CLI layer
pytest integration_tests/cli/ -v

# Just API layer
pytest integration_tests/core/ -v

# One file
pytest integration_tests/cli/test_upload_download.py -v

# Stop on first failure
pytest integration_tests/ -v -x
```

## Safety guarantees

- All test keys are prefixed `drptest-` so they are identifiable at a glance.
- Every test cleans up after itself (teardown deletes what it created), even on failure.
- Tests use an **isolated config dir** (`/tmp/drp-integration-*/`) — they never read
  or write your real `~/.config/drp/` session or config.
- Running against a production DB is fine: the test account's data is touched
  (drops created/deleted), but no other user's data is affected.

## Layout

```
integration_tests/
  conftest.py          shared fixtures (env, session, isolated config, key tracking)
  cli/
    test_upload_download.py   drp up / drp get (text, file, stdin, URL, --url flag)
    test_manage.py            drp rm / drp mv / drp cp / drp renew
    test_browse.py            drp ls / drp status / drp ping / drp diff / drp edit
    test_account.py           drp save / drp load / drp login / drp logout
    test_serve.py             drp serve (directory, glob, multiple files)
    test_parser.py            drp -h / drp --help / drp -V / drp <no args>
  core/
    test_api_text.py          upload_text / get_clipboard (all return paths)
    test_api_file.py          upload_file / get_file (all return paths)
    test_api_actions.py       delete / rename / renew / save_bookmark / list_drops / key_exists
    test_api_auth.py          get_csrf / login
```
