# Dependencies

## External Services

| Service                           | Usage                                                            |
| --------------------------------- | ---------------------------------------------------------------- |
| `id.tradeskillmaster.com`         | OIDC token (Keycloak, `grant_type=password`)                     |
| `app-server.tradeskillmaster.com` | TSM session auth, status, realms2, addon downloads               |
| `*.tradeskillmaster.com`          | CDN blob downloads (per `endpointSubdomains` from auth response) |

Auth: HMAC token = `SHA256("{APP_VERSION}:{time}:{SECRET}")` on every request.

## Python Dependencies

| Package       | Version                      | Purpose                                       |
| ------------- | ---------------------------- | --------------------------------------------- |
| `PySide6`     | latest                       | Qt6 GUI framework                             |
| `aiohttp`     | latest                       | async HTTP client (TSM API)                   |
| `pydantic`    | latest                       | data models + validation                      |
| `apscheduler` | `>=4.0.0a1,<5` (pre-release) | AsyncScheduler (anyio/asyncio)                |
| `aiosqlite`   | latest                       | async SQLite (auction cache)                  |
| `keyring`     | latest                       | OS credential store (Secret Service on Linux) |
| `structlog`   | latest                       | structured logging (bundled in RPM)           |
| `tomli-w`     | latest                       | TOML config writing (bundled in RPM)          |
| `PyYAML`      | latest                       | Lutris `.yml` game config parsing             |

`apscheduler`, `structlog`, `tomli-w` are **bundled** in the RPM under `/usr/lib/tsm-app/`
(not in Fedora/openSUSE repos). Shell wrapper sets `PYTHONPATH=/usr/lib/tsm-app`.

## Packaging

| Format | Build tool            | Target distros              |
| ------ | --------------------- | --------------------------- |
| `.whl` | `python -m build`     | pip install                 |
| `.deb` | `fpm`                 | Ubuntu/Debian               |
| `.rpm` | `fpm` + manual bundle | Fedora, openSUSE Tumbleweed |

RPM entry point: `/usr/bin/tsm-app` (shell wrapper, `#!/bin/sh`).
DEB entry point: Python console script.

## CI Smoke Tests (`.github/workflows/release.yml`)

- `test-deb`: Ubuntu runner, `pip install PySide6 && dpkg -i --ignore-depends=python3-pyside6`
- `test-rpm-fedora`: `fedora:latest` container, `dnf install dist/*.rpm && tsm-app --version`
- `test-rpm-opensuse`: `opensuse/tumbleweed` container, `zypper install dist/*.rpm && tsm-app --version`
- `github-release`: blocked until all three smoke tests pass

## WoW Filesystem Dependencies

```
Requires on-disk:
  <gv_dir>/Interface/AddOns/TSM_AppHelper/   (addon dir must exist to write AppData.lua)
  <gv_dir>/WTF/Account/                      (account scanning for backup/accounting)

Detected via:
  wow/detector.py     filesystem scan + Lutris YAML + Faugus JSON
  wow/utils.py        is_valid_wow_version_dir (checks WoW.exe presence, optional)
```
