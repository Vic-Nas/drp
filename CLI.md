# drp

Drop text and files from the command line — get a link instantly.

```
pip install drp-cli
```

## Usage

```bash
drp setup                  # configure host & log in
drp up "hello world"       # upload clipboard text → prints URL
drp up notes.txt           # upload file → prints /f/key/ URL
drp up doc.pdf -k cv       # upload with custom key
drp get key                # clipboard → stdout (auto-falls back to file)
drp get f/key              # explicitly fetch a file
drp get f/key -o out.pdf   # save file with custom name
drp rm key                 # delete clipboard
drp rm f/key               # delete file
drp mv key newkey          # rename clipboard key
drp mv f/key f/newkey      # rename file key
drp renew key              # renew expiry (paid only)
drp ls                     # list your drops
drp ls -lh                 # long format with sizes and times
drp ls -lh -t f            # list only files
drp ls --export > b.json   # export as JSON (requires login)
drp status                 # show config
drp ping                   # check server connectivity
drp --version              # show version
```

## URLs

| Type      | URL         | Example          |
|-----------|-------------|------------------|
| Clipboard | `/key/`     | `/hello/`        |
| File      | `/f/key/`   | `/f/report/`     |

Clipboards live at `/key/` directly. Files always have the `/f/` prefix.
The CLI uses `f/key` syntax when a file key is needed (e.g. `drp get f/report`).

## How it works

1. `drp setup` saves your host URL (default: `https://drp.vicnas.me`) and optionally logs you in
2. `drp up` detects whether the target is a file or text and uploads accordingly
3. `drp get key` tries clipboard first, then file — or use `f/key` to go straight to the file
4. Anonymous drops have a 24h protection window after creation; after that anyone can rename them
5. Paid drops are locked to your account permanently

## Expiry

| Tier      | Clipboard                  | File             |
|-----------|---------------------------|------------------|
| Anonymous | 24h idle, 7d max lifetime  | 90d from upload  |
| Free      | 48h idle, 30d max lifetime | 90d from upload  |
| Starter   | explicit date (up to 1yr)  | explicit date    |
| Pro       | explicit date (up to 3yr)  | explicit date    |

## Configuration

Config is stored at `~/.config/drp/config.json`:

```json
{
  "host": "https://drp.vicnas.me",
  "email": "you@example.com"
}
```

Session cookies are saved at `~/.config/drp/session.json` — no password prompt on every command.

## Self-hosted

```bash
drp setup
# enter your server URL when prompted
```

See the [server repo](https://github.com/vicnasdev/drp) for deployment instructions.

## License

MIT