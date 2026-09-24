# Packaging

Six formats ship from one repository. The wheel, deb and rpm depend on the
distro's PySide6. The Flatpak and AppImage carry their own Python and Qt, so
they run where no suitable PySide6 exists. The Nix flake builds from nixpkgs.

| Format | Built by | Qt comes from | Notes |
|---|---|---|---|
| wheel | `release.yml` | the user's pip | |
| deb | `release.yml` | apt, Ubuntu 26.04+ | APScheduler 4 bundled |
| rpm | `release.yml` | dnf or zypper | APScheduler 4 bundled |
| AUR | `packaging/PKGBUILD` | `pyside6` package | |
| Flatpak | `packaging.yml` | PySide6 wheel | app id is reverse-DNS |
| AppImage | `packaging.yml` | PySide6 wheel | around 240 MB |
| Nix flake | `packaging.yml` | `python3Packages.pyside6` | |

`packaging.yml` also runs on pushes to `develop` that touch packaging, so a
broken manifest surfaces before a release is tagged rather than during one.

## What is automated, and what is not

Tagging a release builds everything and attaches it to the GitHub release. That
is the whole of the automation for formats that have no store.

| Target | On a tag | Publishing | Needs |
|---|---|---|---|
| wheel, deb, rpm | built and attached | GitHub release only | nothing |
| AppImage | built and attached | GitHub release only | nothing |
| Flatpak bundle | built and attached | GitHub release only | nothing |
| Nix flake | built and checked | nothing to publish | nothing |
| AUR | not built | `aur.yml`, run by hand | `AUR_SSH_KEY`, `AUR_EMAIL` |
| Flathub | not pushed | `flathub.yml`, run by hand | `FLATHUB_TOKEN` |
| nixpkgs | not pushed | pull request, by hand | a nixpkgs pull request |

Three things are worth being clear about:

- **A Nix flake has no store.** `nix run github:exceptionptr/tsm-app-linux`
  resolves the flake straight from the repository as soon as the tag exists.
  Nothing needs publishing. nixpkgs is a separate, optional distribution channel
  that takes a pull request.
- **An AppImage has no store either.** The file on the GitHub release is the
  distribution. [AppImageHub](https://github.com/AppImage/appimage.github.io) is
  an optional catalogue listing, added by a pull request.
- **Flathub cannot be automated for the first release.** It is a pull request
  against `flathub/flathub`, reviewed by a person, and this app additionally
  needs an exception granted for its filesystem permission. Once accepted,
  Flathub creates `flathub/io.github.exceptionptr.tsm-app-linux` and later
  releases go through `flathub.yml`.

### Accounts and secrets

No new accounts beyond GitHub. Flathub and nixpkgs both authenticate with it.

| Secret | Used by | What it is |
|---|---|---|
| `AUR_SSH_KEY`, `AUR_EMAIL` | `aur.yml` | already configured |
| `FLATHUB_TOKEN` | `flathub.yml` | a GitHub token with write access to the Flathub app repository, created after acceptance |

For nixpkgs, add yourself to `maintainers/maintainer-list.nix` in your first pull
request. Afterwards the nixpkgs update bot proposes version bumps on its own.

## Smoke tests

Every package is checked with `--self-test`, not just `--version`. The
difference matters: `--version` returns before PySide6 is ever imported, so it
passes even when Qt is completely broken, which is the failure these bundles are
most prone to. `--self-test` constructs a QApplication and shows a window, then
reports the Python, PySide6 and Qt versions and the platform plugin that loaded.

```bash
QT_QPA_PLATFORM=offscreen tsm-app --self-test
```

It opens no database, reads no keyring, makes no network call and takes no
single instance lock, so it is safe to run while the app is already running, and
it is a useful thing to ask for in a bug report.

CI runs it inside each package: through `flatpak run`, through the AppImage, and
through the Nix wrapper, where it also proves `wrapQtAppsHook` wired the plugin
path up.

## Why PySide6-Essentials

The Flatpak and AppImage install `PySide6-Essentials` rather than `PySide6`. The
app imports only QtCore, QtGui, QtNetwork, QtSvg and QtWidgets, all of which are
in Essentials. The Addons half carries QtWebEngine and QtMultimedia and would add
several hundred megabytes for nothing.

## Flatpak

```bash
flatpak install -y flathub org.kde.Sdk//6.11 org.kde.Platform//6.11
flatpak-builder --force-clean --user --install build \
  packaging/flatpak/io.github.exceptionptr.tsm-app-linux.yml
```

The KDE runtime is used rather than the freedesktop one because it is built to
run Qt 6 applications, so the X11 libraries Qt needs are all present. Qt 6.5 and
later will not load the xcb platform plugin without `libxcb-cursor`.

`flatpak-builder` builds offline, so every wheel is named in
`packaging/flatpak/python3-deps.yaml` with its hash. Regenerate after changing
dependencies in `pyproject.toml`:

```bash
python scripts/flatpak_gen_deps.py
```

The generated lists carry wheels for more than one Python version so pip can
pick a matching one whichever Python the runtime ships. Most wheels are pure
Python or `abi3` and work anywhere; eight are built per version.

### App id

`io.github.exceptionptr.tsm-app-linux`, matching the repository name. Flathub
derives a repository URL from the last component of the id and requires it to
resolve, so `io.github.exceptionptr.tsm-app` would not work: it points at
`github.com/exceptionptr/tsm-app`, which does not exist. The deb, rpm, AUR and
AppImage builds keep the plain `tsm-app` name so existing installs are undisturbed.

### Submitting to Flathub

1. Fork `flathub/flathub` and create a branch named after the app id.
2. Copy `packaging/flatpak/*` into the repository root.
3. Pin the `commit` alongside the `tag` in the manifest. The release workflow
   does this automatically for its own builds, but Flathub wants it committed.
4. Open a pull request against the `new-pr` branch.
5. **Request a filesystem exception.** `--filesystem=host` is an error for the
   Flathub linter and needs a granted exception. The justification: the app
   exists to write Lua files into World of Warcraft installs, and those live
   wherever the user keeps games, including Wine prefixes, Lutris and Steam
   libraries and separate drives such as `/mnt/games`. It also reads Lutris and
   Faugus launcher configuration to find them. No narrower permission can
   express "wherever the user installed the game".

### Sandbox limitation

A Flatpak has no access to the X session manager, so inside the sandbox Qt is
not session managed and never receives `commitDataRequest`. The logout fix in
`tsm/ui/_window_close.py` therefore does nothing there. It also cannot cause the
problem it fixes, because there is no session manager client to refuse a request.

## AppImage

```bash
scripts/build_appimage.sh [path/to/tsm_app-*.whl]
```

Without an argument it builds a wheel from the working tree. The dependency list
is derived from `pyproject.toml`, so it cannot drift.

Two things to know before editing the script:

- **Requirements must be exact `==` pins.** python-appimage joins its pip
  arguments into one shell string without quoting them, so `>=` or `<` is read as
  a redirect and the constraint is silently dropped:
  `PySide6-Essentials>=6.6.0` installs whatever is newest and leaves a file
  called `=6.6.0`. `scripts/appimage_pins.py` resolves exact pins and refuses to
  emit anything containing shell metacharacters.
- **Packaging runs separately from assembly.** python-appimage names its output
  after the desktop file's `Name`, which is `TSM Desktop App`, while
  `appimagetool` replaces the spaces with underscores, so letting it package the
  bundle fails on a file it cannot find. The script assembles the AppDir with
  `--no-packaging` and runs `appimagetool` itself.

Users without FUSE need `APPIMAGE_EXTRACT_AND_RUN=1`.

### Host libraries

The bundle carries Python and Qt but links against system libraries it does not
ship. Read off `ldd` against the bundled Qt libraries in a bare Ubuntu container:

| Needed for | Libraries |
|---|---|
| any use, including offscreen | `libglib-2.0`, `libgthread-2.0`, `libgssapi_krb5`, `libGL`, `libEGL`, `libfontconfig`, `libdbus-1`, `libxkbcommon` |
| an X11 desktop | `libxcb-cursor`, `libxcb-icccm`, `libxcb-image`, `libxcb-keysyms`, `libxcb-render`, `libxcb-render-util`, `libxcb-shape`, `libxcb-util`, `libxcb-xkb`, `libxkbcommon-x11` |

Without glib, PySide6 does not import at all. Any desktop installation has the
lot; a container does not, which is why the CI smoke test installs them.

Only the AppImage has this exposure. The Flatpak runs inside the KDE runtime,
which provides them, and the Nix package gets them through its closure.

## Nix

```bash
nix flake check --all-systems   # evaluates every output
nix build .#tsm-app
nix run .
nix develop                     # dev shell with pytest, ruff and mypy
```

`flake.lock` pins nixpkgs. Update it with `nix flake update`.

APScheduler 4 is still a pre-release, so nixpkgs carries 3.x while the app uses
the 4.x `AsyncScheduler` API. The flake defines `apscheduler4` itself and exposes
it as a package, so it can be reused or dropped once nixpkgs has it.

A Qt application needs its plugin paths wired up, which `buildPythonApplication`
does not do. `qt6.wrapQtAppsHook` is added with `dontWrapQtApps = true`, and its
arguments are folded into the wrapper the Python builder already creates.

### Submitting to nixpkgs

`packaging/nixpkgs/package.nix` is ready to copy to
`pkgs/by-name/ts/tsm-app/package.nix`. It fetches a release tarball instead of
the working tree and takes its dependencies as arguments. Before opening the
pull request:

1. Replace `lib.fakeHash` with the real hash:
   `nix-prefetch-url --unpack https://github.com/exceptionptr/tsm-app-linux/archive/refs/tags/v1.1.16.tar.gz`
2. Add yourself to `meta.maintainers`.
3. Consider submitting `apscheduler_4` as its own package first. Reviewers
   generally prefer a shared dependency over one vendored into an application.
