# TSM App for Linux

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![PySide6](https://img.shields.io/badge/UI-PySide6-green)
![License MIT](https://img.shields.io/badge/license-MIT-lightgrey)

TradeSkillMaster Desktop App Linux port. Authenticates with the TSM API, downloads auction data, and writes `AppData.lua` for the TSM addon running under Wine/Lutris/Steam.

## Screenshots

### Main window

| | |
|---|---|
| ![](media/1.png) | ![](media/2.png) |
| ![](media/3.png) | ![](media/4.png) |

### Settings

| | | |
|---|---|---|
| ![](media/5.png) | ![](media/6.png) | ![](media/7.png) |

## Features

- TSM account login with secure credential storage (keyring / Secret Service)
- Automatic auction data sync every 5 minutes (differential - only changed blobs downloaded); manual refresh on demand
- WoW install auto-detection for Wine, Lutris, Faugus Launcher, Steam, and custom paths
- Atomic `AppData.lua` writes: no partial/corrupt addon data
- Scheduled SavedVariables backups with restore support
- TSM addon version checking with auto-update on each sync; manual install, update, and uninstall per addon per game version from the Addon Versions tab
- Accounting tab: browse sales, purchases, income, and expenses from WoW SavedVariables with date filtering, paginated preview (50 rows/page), item names resolved via Wowhead API with WoW-style tooltips on hover, and CSV export
- Status bar with GitHub link and Settings shortcut; system tray icon with minimise-to-tray support

## Requirements

- Python 3.11+
- PySide6 (Qt6)
- World of Warcraft running via Wine, Lutris, or Steam on Linux

## Installation

### Arch Linux

```bash
# Via AUR helper (recommended)
paru -S tsm-app

# Or manually
git clone https://aur.archlinux.org/tsm-app.git
cd tsm-app
makepkg -si
```

### Debian / Ubuntu 26.04+

The `.deb` package requires **Ubuntu 26.04 or later** - PySide6 is only available
via apt on 26.04+, and APScheduler 4.x (not in Ubuntu repos) is bundled inside the package.

Download the `.deb` from the [latest release](https://github.com/exceptionptr/tsm-app-linux/releases/latest):

```bash
sudo apt install ./tsm-app_*_all.deb
```

**Ubuntu 24.04 or earlier:** PySide6 is not in the apt repos on these versions.
Install via pip into a virtual environment instead - see [From source / pip wheel](#any-distro--from-source) below.

### Fedora / RHEL / openSUSE

Download the `.rpm` from the [latest release](https://github.com/exceptionptr/tsm-app-linux/releases/latest):

```bash
sudo dnf install tsm-app-*.noarch.rpm
```

### Any distro / From source

Recommended for Ubuntu 24.04 and distros without a compatible PySide6 package:

```bash
# From the pre-built wheel (no git required)
python3 -m venv .venv
source .venv/bin/activate
pip install tsm_app-*.whl   # download .whl from the latest release

# Or from source
git clone https://github.com/exceptionptr/tsm-app-linux
cd tsm-app-linux
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Run

```bash
python -m tsm
# or after package / pip install:
tsm-app
```

### Headless Mode (Terminal & Automation)

The app supports a fully functional headless mode designed for command-line use and automation (e.g. via `cron` or systemd timers) without any PySide6/Qt GUI dependencies.

#### CLI Arguments:
* `--headless`: Explicitly run in headless mode.
* `-l`, `--login`: Interactive registration (sign-up) and authentication (login) in the terminal.
* `-s`, `--sync`: Run a single synchronization pass (download auction data + check/install addon updates) and exit.
* `-b`, `--backup`: Run a single SavedVariables backup pass and exit.
* `-i`, `--install-addons`: Download and install/bootstrap TSM addons for all detected WoW game versions.
* `--wow-path <path>`: Configure/update the WoW base directory path in the configuration file.
* `--skip-detection`: Skip auto-scanning the filesystem for WoW paths.

*Note: Headless mode is implicitly enabled if any headless-specific flag (`--login`, `--sync`, `--backup`, `--install-addons`, `--wow-path`) is specified.*

#### Getting Started (Sign-up, Auth & Addon Installation):
1. Run the login command:
   ```bash
   tsm-app --login
   ```
2. Select Option 2 to register a new account on the TSM website (which will be opened in your browser), or Option 1 to log in. Enter your credentials securely in the terminal; they will be stored securely via the keyring.

3. **Install TSM Addons:** By default, `--sync` only updates addons that are **already installed** in your `Interface/AddOns` folder to avoid installing unwanted addons on clients you do not play. 
   
   If you have a fresh WoW install, run the app once with:
   ```bash
   tsm-app --install-addons
   ```
   This will download and install both `TradeSkillMaster` and `TradeSkillMaster_AppHelper` for all detected game versions.

#### Automation / Cronjob Setup:
Since system keyrings may not be available in non-interactive/cron shell sessions, pass your credentials using `TSM_EMAIL` and `TSM_PASSWORD` environment variables:

```cron
# Run TSM synchronization every hour
0 * * * * TSM_EMAIL="user@example.com" TSM_PASSWORD="securepassword" /home/username/src/tsm-app-linux/.venv/bin/tsm-app --sync
```

## File Locations

| Purpose       | Path                                          |
| ------------- | --------------------------------------------- |
| Config        | `~/.config/tsm-app/config.toml`               |
| Database      | `~/.local/share/tsm-app/data.db`              |
| Log file      | `~/.local/share/tsm-app/logs/tsm-app.log`     |
| Backups       | `~/.local/share/tsm-app/backups/`             |
| Item cache    | `~/.local/share/tsm-app/item_cache.json`      |

Logs rotate automatically; the last 5 files are kept. To reset the app to a clean
state, remove `~/.config/tsm-app/` and `~/.local/share/tsm-app/`.

## WoW Detection

The app scans the following paths automatically on startup:

| Source                  | Path                                                                                          |
| ----------------------- | --------------------------------------------------------------------------------------------- |
| Wine (default prefix)   | `~/.wine/drive_c/Program Files (x86)/World of Warcraft`                                      |
| Wine (default prefix)   | `~/.wine/drive_c/Program Files/World of Warcraft`                                             |
| Lutris (common)         | `~/Games/world-of-warcraft`                                                                   |
| Lutris (common)         | `~/Games/World of Warcraft`                                                                   |
| Lutris (config)         | Wine prefix read from `~/.local/share/lutris/games/*.yml`, both Program Files variants        |
| Faugus Launcher (config)| Wine prefix read from `~/.config/faugus-launcher/games.json`, both Program Files variants    |
| Faugus Launcher (common)| All subdirectories of `~/Faugus/`, both Program Files variants                               |
| Steam                   | `~/.local/share/Steam/steamapps/common/World of Warcraft`                                    |
| Snap Wine               | `~/snap/wine-platform-5-stable/common/.wine/drive_c/Program Files (x86)/World of Warcraft`   |
| Mount (games partition) | `/mnt/games/World of Warcraft`                                                                |
| System opt              | `/opt/games/World of Warcraft`                                                                |

If your WoW installation isn't detected automatically, add the path manually via **Settings -> WoW Installations**.

## Architecture

| Layer        | Module                          | Purpose                                              |
| ------------ | ------------------------------- | ---------------------------------------------------- |
| Entry point  | `tsm/__main__.py`, `tsm/app.py` | QApplication setup, dependency wiring                |
| Async runner | `tsm/workers/async_runner.py`   | Dedicated asyncio loop on a QThread                  |
| Bridge       | `tsm/workers/bridge.py`         | Submit coroutines, emit Qt signals with results      |
| Scheduler    | `tsm/core/scheduler.py`         | APScheduler 4.x periodic jobs                        |
| Services     | `tsm/core/services/`            | Auth, auction data, backup, addon updater            |
| Storage      | `tsm/storage/`                  | SQLite cache, TOML config, keyring secrets           |
| WoW          | `tsm/wow/`                      | Install detection, Lua writer, SavedVariables reader |
| UI           | `tsm/ui/`                       | MVVM views + viewmodels (PySide6)                    |
| API client   | `tsm/api/client.py`             | aiohttp TSM API client with retry logic              |

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check tsm/ tests/

# Type check
mypy tsm/

# Build wheel
python -m build --wheel
```

## Acknowledgements

Big thanks to the [TradeSkillMaster](https://tradeskillmaster.com/) team for building and maintaining the TSM ecosystem: the addon, the API, and the auction data infrastructure that makes all of this possible.

## License

MIT
