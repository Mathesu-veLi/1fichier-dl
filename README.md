# 1Fichier-dl CLI

A command line version of [1Fichier-dl](https://github.com/Leinad4Mind/1fichier-dl)
for downloading files from 1fichier share links on Linux. It was prepared for
[CachyOS](https://cachyos.org/) (Arch-based), but works on any distribution with
Python 3.9 or newer.

This is a fork of the original GUI project. The PyQt5 interface is still in the
repository, but the default workflow is now terminal-first and does not require
Qt to be installed.

## Features

- Download one or more 1fichier links from the terminal.
- Show file name, size and password protection with `--info`.
- Prompt for passwords of protected files (or accept `--password`).
- Resume interrupted downloads from `.unfinished` files.
- Skip files that are already complete and protect existing files by default.
- Optional HTTP/SOCKS proxy for connections that are rate-limited by 1fichier.
- Preserve the `af` affiliate cookie embedded in share links.
- Friendly exit codes for scripts: `0` success, `1` failure, `130` interrupt.

## Install on CachyOS

CachyOS follows Arch Linux packaging rules and marks the system Python as
externally managed (PEP 668). Use `pipx` or a virtual environment instead of
`sudo pip install`.

### With pipx (recommended)

```bash
sudo pacman -S --needed python python-pipx
git clone https://github.com/Mathesu-veLi/1fichier-dl.git
cd 1fichier-dl
pipx install .
```

To install straight from GitHub:

```bash
pipx install git+https://github.com/Mathesu-veLi/1fichier-dl.git
```

Both `1fichier-dl` and `1fichier-dl-cli` are available after installation.

### Development virtual environment

```bash
git clone https://github.com/Mathesu-veLi/1fichier-dl.git
cd 1fichier-dl
python -m venv .venv
source .venv/bin/activate
pip install -e .
1fichier-dl --help
```

`python 1fichier-dl.py` also works from a checkout and uses the same CLI.

## Usage

```bash
# Download to ~/Downloads
1fichier-dl 'https://1fichier.com/?sxosmk9m8rxcll2l08mx&af=4186346'

# Choose the output directory and file name
1fichier-dl -o ~/Videos --filename episode.mkv 'https://1fichier.com/?FILE_ID'

# Inspect a link without downloading it
1fichier-dl --info 'https://1fichier.com/?sxosmk9m8rxcll2l08mx&af=4186346'

# Protected file: pass the password or let the CLI prompt for it
1fichier-dl -p 'the-password' 'https://1fichier.com/?FILE_ID'

# Route requests through a proxy
1fichier-dl --proxy socks5h://127.0.0.1:1080 'https://1fichier.com/?FILE_ID'

# Replace a file that already exists
1fichier-dl --overwrite 'https://1fichier.com/?FILE_ID'
```

### Options

| Option | Description |
| --- | --- |
| `-o, --output-dir DIR` | Directory for downloaded files (default: `~/Downloads`). |
| `--filename NAME` | Save a single link under this name. |
| `-p, --password PASS` | Password for protected files. |
| `--info` | Print name, size and password status only. |
| `--timeout SECONDS` | HTTP timeout (default: `30`). |
| `--proxy URL` | HTTP or SOCKS proxy, for example `socks5h://127.0.0.1:1080`. |
| `--proxy-file FILE` | Proxies to try in order, one per line. |
| `--overwrite` | Replace an existing complete file. |
| `-v, --verbose` | Show debug logging. |
| `--version` | Print the installed version. |

### Resuming and partial files

Downloads are written to `<name>.unfinished` and renamed only after the transfer
finishes. Run the same command again to resume from the current offset (the
server must support HTTP range requests). If a complete file with the same name
exists and its size matches the server, the download is skipped; otherwise the
CLI refuses to replace it unless `--overwrite` is passed.

### 1fichier rate limits

1fichier throttles free downloads per IP address and may ask you to wait before
the next download. The CLI reports the advertised wait time instead of silently
retrying. Use `--proxy`, `--proxy-file` or wait when that happens. Proxies are
not used by default, unlike the old GUI behavior.

### Proxy rotation

Create a text file with one proxy per line. Blank lines and lines starting with
`#` are ignored, duplicates are removed, and entries without a scheme are
treated as HTTP proxies:

```text
# proxies.txt
socks5h://127.0.0.1:1080
http://user:password@10.0.0.5:8080
203.0.113.10:3128
```

Then pass the file to the CLI:

```bash
1fichier-dl --proxy-file proxies.txt -o ~/Downloads 'https://1fichier.com/?FILE_ID'
```

For each link the CLI tries the proxies in order and moves to the next one when
a proxy fails to connect or when 1fichier replies with its rate-limit page.
Passwords, dead links and existing destination files stop the attempt instead
of burning through the list. `--proxy` and `--proxy-file` are mutually
exclusive. Keep proxy files containing credentials readable only by you
(`chmod 600 proxies.txt`).

### Refreshing the proxy list

The repository ships source lists in `https_proxy_list.txt` and
`socks5_proxy_list.txt`. The refresher resolves those sources, validates each
proxy and writes a flat list that `--proxy-file` can read:

```bash
1fichier-dl-refresh-proxies --output proxies-fresh.txt
```

Useful options:

| Option | Description |
| --- | --- |
| `--limit N` | Test only the first N candidates. |
| `--max N` | Stop after finding N working proxies. |
| `--workers N` | Parallel validations (default: `100`). |
| `--timeout SECONDS` | Per-request timeout (default: `8`). |
| `--source-file FILE` | Use a custom source file (repeatable). |
| `--source URL` | Add a source URL or direct proxy (repeatable). |
| `--shuffle` | Shuffle candidates before testing. |

By default each proxy only has to load the 1fichier home page. To require a real
download from a specific file link, pass the link and `--check-download`:

```bash
1fichier-dl-refresh-proxies \
  --test-url 'https://1fichier.com/?FILE_ID' \
  --check-download \
  --max 3 \
  --output proxies-download.txt
```

`--check-download` requests a direct link and reads one byte, so it consumes
that proxy's free-download window. Add `--password` if the file is protected.

A source file can contain raw list URLs (like the bundled files) or direct
proxies. Free proxies are ephemeral and often become rate-limited within
minutes: run the refresher again when the list goes stale. For large files a
VPN or a Premium account is still the reliable option.

## GUI (legacy)

The original PyQt5 interface is still available from a checkout:

```bash
pip install -e '.[gui]'
python 1fichier-dl-gui.py
```

Qt dependencies are optional and are not installed by the plain CLI package.

## Development

```bash
pip install -e '.[dev]'
pytest
```

The tests start a small local HTTP server that mimics the 1fichier file page, so
they do not need network access or an account.

## Credits

- Original project by [manuGMG](https://github.com/manuGMG), later maintained by
  [Leinad4Mind](https://github.com/Leinad4Mind/1fichier-dl).
- GUI icon and screenshot assets come from the upstream project.
- Free proxy lists, when enabled by the GUI, come from the upstream project's
  sources.

## License

GNU General Public License v2. See [LICENSE](LICENSE).

For a plain virtual environment, the CLI runtime dependencies are also listed in
`requirements-cli.txt`; `requirements-dev.txt` adds the test runner.
