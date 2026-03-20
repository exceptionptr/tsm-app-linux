"""UpdateService: check for and install TSM addon updates.

Original behaviour (from MainThread.pyc + WoWHelper.pyc):
- Called on every status poll (60 min) with the `addons` list from the status API
- Each entry: {name: str, version_str: str}  (base name, no suffix)
- Empty version_str → delete that addon from all game version dirs
- Dev versions (@project-version@) are never auto-updated
- Download: GET /v2/addon/{base_name}?channel=...&tsm_version=...  → zip bytes
- Zip contains base_name/ as top-level folder
- Install: rmtree existing folder, extractall into AddOns dir
- One download per base addon; installed into every game version dir where it exists
"""

from __future__ import annotations

import logging
import shutil
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from tsm.api.types import AddonVersionInfo
from tsm.wow.utils import iter_wow_gv_roots

logger = logging.getLogger(__name__)


def _find_addons_dir(gv_path: Path) -> Path | None:
    for name in ("AddOns", "Addons"):
        d = gv_path / "Interface" / name
        if d.is_dir():
            return d
    return None


def _toc_version(toc_path: Path) -> tuple[int, str]:
    """Returns (version_type, version_str).  0=missing, 1=release, 2=dev."""
    try:
        for line in toc_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("## Version:"):
                ver = line.split(":", 1)[1].strip()
                if ver in ("@project-version@", "@tsm-project-version@"):
                    return (2, "Dev")
                return (1, ver)
    except OSError:
        pass
    return (0, "")


class UpdateService:
    def __init__(self, api_client=None, wow_detector=None):
        self._client = api_client
        self._detector = wow_detector

    async def check_and_update(self, addon_versions: list[AddonVersionInfo]) -> list[str]:
        """Compare installed TOC versions against the status API list.
        Downloads and installs outdated addons.
        Returns list of base addon names that were actually updated."""
        if not addon_versions or self._client is None or self._detector is None:
            return []

        installs = self._detector.installs if self._detector is not None else []
        if not installs:
            return []

        updated: list[str] = []
        for addon in addon_versions:
            base_name = addon.get("name", "")
            latest_version = addon.get("version_str", "")
            if not base_name:
                continue

            if latest_version == "":
                await self._delete_addon(base_name, installs)
                continue

            if self._needs_update(base_name, latest_version, installs):
                ok = await self._download_and_install(base_name, latest_version, installs)
                if ok:
                    updated.append(base_name)

        return updated

    # ── Internals ──────────────────────────────────────────────────────

    def _needs_update(self, base_name: str, latest: str, installs) -> bool:
        """True if any installed copy of this addon is outdated (release version ≠ latest)."""
        for wow_root, gv_dir in iter_wow_gv_roots(installs):
            addons_dir = _find_addons_dir(wow_root / gv_dir)
            if addons_dir is None:
                continue
            toc = addons_dir / base_name / f"{base_name}.toc"
            vtype, installed_ver = _toc_version(toc)
            if vtype == 1 and installed_ver != latest:
                return True
        return False

    async def _download_and_install(self, base_name: str, latest: str, installs) -> bool:
        """Download zip for base_name and install into every game version dir
        where the addon folder already exists."""
        assert self._client is not None
        logger.info("Downloading addon %s v%s", base_name, latest)
        try:
            zip_bytes = await self._client.addon.download(base_name, tsm_version=latest)
        except Exception:
            logger.exception("Failed to download addon %s", base_name)
            return False

        try:
            zf = ZipFile(BytesIO(zip_bytes))
        except BadZipFile:
            logger.error("Downloaded file for %s is not a valid zip", base_name)
            return False

        installed_any = False
        with zf:
            for wow_root, gv_dir in iter_wow_gv_roots(installs):
                addons_dir = _find_addons_dir(wow_root / gv_dir)
                if addons_dir is None:
                    continue
                addon_dir = addons_dir / base_name
                if not addon_dir.exists():
                    continue  # only update where already installed
                try:
                    shutil.rmtree(addon_dir)
                    zf.extractall(addons_dir)
                    logger.info("Installed %s v%s → %s", base_name, latest, addons_dir)
                    installed_any = True
                except Exception:
                    logger.exception("Failed to install %s to %s", base_name, addons_dir)

        return installed_any

    async def _delete_addon(self, base_name: str, installs) -> None:
        """Remove addon folder from all game version dirs (version_str == "" signal)."""
        for wow_root, gv_dir in iter_wow_gv_roots(installs):
            addons_dir = _find_addons_dir(wow_root / gv_dir)
            if addons_dir is None:
                continue
            addon_dir = addons_dir / base_name
            if addon_dir.exists():
                try:
                    shutil.rmtree(addon_dir)
                    logger.info("Deleted addon %s from %s", base_name, addons_dir)
                except Exception:
                    logger.exception("Failed to delete %s", addon_dir)
