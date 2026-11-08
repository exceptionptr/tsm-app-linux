"""UpdateService: keep the TSM addons current, as the official 1.0.9 client does.

The socket's ``addon`` event lists the current release of each addon:

    {"data": [{"addon": "TradeSkillMaster", "channel": "release",
               "version": "v4.15.4", "url": "<zip>"}, ...], "isComplete": true}

Since TSM 4.15 every addon is one multi-toc package that serves all game
versions, so one zip is downloaded per addon and installed into each game
version folder. Rules taken from the official installer:

- an addon folder holding .git is a developer checkout and never touched
- the installed version is read from <AddOns>/<name>/<name>.toc (names matched
  case-insensitively), and a leading "v" is ignored when comparing
- an @project-version@ toc is a dev build and is left alone
- install = delete the old folder, extract the zip into AddOns

Automatic updates only touch game versions where the addon is already
installed; the Addon Versions tab installs into a new one on request.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from tsm.api.types import AddonRelease
from tsm.core.services._zip_utils import safe_extractall
from tsm.wow.game_versions import BY_FOLDER, SUFFIX_BY_FOLDER
from tsm.wow.utils import is_valid_wow_version_dir, iter_wow_gv_roots, normalize_wow_base

logger = logging.getLogger(__name__)

_DEV_VERSIONS = ("@project-version@", "@tsm-project-version@")
_FOLDER_BY_SUFFIX = {s: f for f, s in SUFFIX_BY_FOLDER.items()}
_SUFFIXES_BY_LENGTH = sorted(_FOLDER_BY_SUFFIX, key=len, reverse=True)


def split_suffix(name: str) -> tuple[str, str]:
    """("TradeSkillMaster-Forever") -> ("TradeSkillMaster", "_forever_").

    The Addon Versions tab names a row by addon plus game version suffix.
    """
    for s in _SUFFIXES_BY_LENGTH:
        if s and name.endswith(s):
            return name[: -len(s)], _FOLDER_BY_SUFFIX[s]
    return name, "_retail_"


def _norm(version: str) -> str:
    v = version.strip()
    return v[1:] if v[:1] in ("v", "V") else v


def _ci(parent: Path, name: str) -> Path | None:
    p = parent / name
    if p.exists():
        return p
    try:
        low = name.lower()
        for c in parent.iterdir():
            if c.name.lower() == low:
                return c
    except OSError:
        pass
    return None


def find_addons_dir(gv_path: Path) -> Path | None:
    iface = _ci(gv_path, "Interface")
    if iface is None:
        return None
    d = _ci(iface, "AddOns")
    return d if d is not None and d.is_dir() else None


def toc_version(addon_dir: Path) -> tuple[int, str]:
    """(version_type, version) for an addon folder. 0=missing, 1=release, 2=dev."""
    toc = _ci(addon_dir, addon_dir.name + ".toc")
    if toc is None:
        return (0, "")
    try:
        for line in toc.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("## Version:"):
                ver = line.split(":", 1)[1].strip()
                if ver in _DEV_VERSIONS:
                    return (2, "Dev")
                return (1, ver)
    except OSError:
        pass
    return (0, "")


def _zip_version(zf: ZipFile, addon: str) -> str:
    for n in zf.namelist():
        parts = n.split("/")
        if len(parts) == 2 and parts[1].lower() == f"{addon}.toc".lower():
            for line in zf.read(n).decode("utf-8", "ignore").splitlines():
                if line.startswith("## Version:"):
                    return line.split(":", 1)[1].strip()
    return ""


class UpdateService:
    def __init__(self, api_client: Any = None, wow_detector: Any = None):
        self._client = api_client
        self._detector = wow_detector
        self._releases: dict[str, AddonRelease] = {}
        self._lock: asyncio.Lock | None = None

    @property
    def releases(self) -> dict[str, AddonRelease]:
        return dict(self._releases)

    def set_releases(self, releases: list[AddonRelease]) -> None:
        self._releases = {r["addon"]: r for r in releases if r.get("addon") and r.get("url")}

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def check_and_update(self, releases: list[AddonRelease] | None = None) -> list[str]:
        """Update every installed copy that is behind. Returns the addons updated."""
        if releases is not None:
            self.set_releases(releases)
        if self._client is None or self._detector is None or not self._releases:
            return []
        installs = self._detector.installs
        if not installs:
            return []
        updated: list[str] = []
        async with self._get_lock():
            for name, rel in self._releases.items():
                targets = []
                for base, gv in iter_wow_gv_roots(installs):
                    addons_dir = find_addons_dir(base / gv)
                    if addons_dir is None:
                        continue
                    addon_dir = _ci(addons_dir, name)
                    if addon_dir is None or not addon_dir.is_dir():
                        continue
                    if self._needs_install(addon_dir, rel["version"]):
                        targets.append(addons_dir)
                if targets and await self._install(rel, targets):
                    updated.append(name)
        return updated

    @staticmethod
    def _needs_install(addon_dir: Path, version: str) -> bool:
        if (addon_dir / ".git").exists():
            logger.info("%s is a git checkout, not updating", addon_dir)
            return False
        vtype, installed = toc_version(addon_dir)
        if vtype == 2:
            return False
        return _norm(installed) != _norm(version)

    async def _install(self, rel: AddonRelease, addons_dirs: list[Path]) -> bool:
        assert self._client is not None
        name = rel["addon"]
        logger.info("Downloading %s %s", name, rel["version"])
        try:
            raw = await self._client.download(rel["url"])
        except Exception:
            logger.exception("Failed to download %s", name)
            return False
        if not raw:
            logger.error("%s: download URL answered 404", name)
            return False
        try:
            zf = ZipFile(BytesIO(raw))
        except BadZipFile:
            logger.error("Downloaded file for %s is not a valid zip", name)
            return False
        ok = False
        with zf:
            if not any(n.split("/")[0] == name for n in zf.namelist()):
                logger.error("Zip for %s has no %s/ folder", name, name)
                return False
            logger.debug("%s zip toc version: %s", name, _zip_version(zf, name))
            for addons_dir in addons_dirs:
                try:
                    existing = _ci(addons_dir, name)
                    if existing is not None:
                        await asyncio.to_thread(shutil.rmtree, existing)
                    await asyncio.to_thread(safe_extractall, zf, addons_dir)
                    logger.info("Installed %s %s -> %s", name, rel["version"], addons_dir)
                    ok = True
                except Exception:
                    logger.exception("Failed to install %s to %s", name, addons_dir)
        return ok

    async def install_or_update_addon(self, name: str, version: str = "") -> bool:  # noqa: ARG002
        """Install one addon into one game version, creating AddOns if needed.

        ``name`` carries the game version suffix the Addon Versions tab uses,
        e.g. "TradeSkillMaster_AppHelper-Forever".
        """
        if self._client is None or self._detector is None:
            return False
        base_name, folder = split_suffix(name)
        rel = self._releases.get(base_name)
        if rel is None or folder not in BY_FOLDER:
            logger.warning("No release known for %s yet", base_name)
            return False
        targets = []
        for install in self._detector.installs:
            gv_path = normalize_wow_base(Path(install.path)) / folder
            addons_dir = find_addons_dir(gv_path)
            if addons_dir is None:
                if not is_valid_wow_version_dir(gv_path):
                    continue
                addons_dir = gv_path / "Interface" / "AddOns"
                addons_dir.mkdir(parents=True, exist_ok=True)
            existing = _ci(addons_dir, base_name)
            if existing is not None and (existing / ".git").exists():
                logger.info("%s is a git checkout, not replacing", existing)
                continue
            targets.append(addons_dir)
        if not targets:
            return False
        async with self._get_lock():
            return await self._install(rel, targets)
