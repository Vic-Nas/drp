# drp

Drop text and files from the command line — get a link instantly.

```
pip install drp-cli
```

## Usage

```bash
drp setup              # configure host & log in
drp up notes.txt       # upload a file → prints URL
drp up "hello world"   # upload text → prints URL
drp up doc.pdf -k cv   # upload with a custom key
drp get mykey          # text → stdout, file → saved to disk
drp get mykey -o a.txt # save file with custom name
drp rm mykey           # delete a drop
drp mv mykey newkey    # rename a drop
drp renew mykey        # renew a drop's expiry (paid)
drp ls                 # list your drops (requires login)
drp status             # show config
drp --version          # show version
```

## How it works

1. `drp setup` saves your host URL (default: `https://drp.vicnas.me`) and optionally logs you in
2. `drp up` uploads a file or text string and prints the shareable URL
3. `drp get` retrieves a drop — text is printed to stdout, files are saved to disk
4. Works anonymously or logged in — logged-in users get locked drops, longer expiry, and `drp ls`

## Configuration

Config is stored at `~/.config/drp/config.json`:

```json
{
  "host": "https://drp.vicnas.me",
  "email": "you@example.com"
}
```

## Self-hosted

Point the CLI at your own instance:

```bash
drp setup
# enter your server URL when prompted
```

See the [server repo](https://github.com/vicnasdev/drp) for deployment instructions.

## License

MIT
