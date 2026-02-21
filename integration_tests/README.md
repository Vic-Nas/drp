# drp integration tests

Real end-to-end tests against a live drp server and B2 bucket.
**Not run by CI** — run manually.

## Setup

No manual setup. Tests read your existing `.env` and create/delete
test users automatically via `manage.py`.

```bash
pytest integration_tests/ -v
```

Three users are created at session start and deleted at the end:

| fixture        | email                      | plan    |
|----------------|----------------------------|---------|
| `free_user`    | test-free@{DOMAIN}         | FREE    |
| `starter_user` | test-starter@{DOMAIN}      | STARTER |
| `pro_user`     | test-pro@{DOMAIN}          | PRO     |
| `anon`         | —                          | none    |

## Running

```bash
pytest integration_tests/ -v          # everything
pytest integration_tests/cli/ -v      # CLI layer only
pytest integration_tests/core/ -v     # API layer only
pytest integration_tests/ -v -x       # stop on first failure
pytest integration_tests/core/test_api_access.py -v  # one file
```

## Safety

- All test keys are prefixed `drptest-` and deleted at session end.
- Test users are ephemeral — created and deleted each run.
- Uses isolated `/tmp/drp-integration-*/` config dirs — `~/.config/drp/` untouched.
- Safe against production DB — test users' data only.

## Fixtures quick reference

```python
# API-level (requests.Session)
def test_something(free_user, starter_user, pro_user, anon):
    free_user.session   # authenticated requests.Session
    free_user.email     # test-free@domain
    free_user.plan      # 'FREE'
    free_user.track(key, ns='c')  # registers key for cleanup

# CLI-level (subprocess env dicts)
def test_cli(cli_envs, anon_cli_env):
    cli_envs['free']     # env dict for free user
    cli_envs['starter']  # env dict for starter user
    cli_envs['pro']      # env dict for pro user
    anon_cli_env         # env dict for unauthenticated user
```

## Layout

```
integration_tests/
  conftest.py                 user creation, fixtures, key tracking
  cli/
    test_upload_download.py   drp up / drp get
    test_manage.py            drp rm / mv / cp / renew
    test_browse.py            drp ls / status / ping / diff / edit
    test_account.py           drp save / drp load / drp login / drp logout
    test_serve.py             drp serve
    test_parser.py            drp -h / --help / -V / no args
  core/
    test_api_auth.py          get_csrf / login
    test_api_text.py          upload_text / get_clipboard
    test_api_file.py          upload_file / get_file
    test_api_actions.py       delete / rename / renew / save_bookmark / list_drops / key_exists
    test_api_access.py        cross-user and anon access / ownership enforcement
    test_api_plans.py         plan-gated features (burn, expiry, password, renew, file size)
```
