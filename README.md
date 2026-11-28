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
the next download. The CLI reports this case instead of silently retrying. Use
`--proxy` with a working proxy (or wait) when that happens. Proxies are not used
by default, unlike the old GUI behavior.

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
