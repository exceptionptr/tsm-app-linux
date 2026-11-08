"""UpdateService: one multi-toc zip per addon, installed into each game version."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tsm.core.services.updater import UpdateService, split_suffix


def _zip(name: str, version: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}/{name}.toc", f"## Title: {name}\n## Version: {version}\n")
        zf.writestr(f"{name}/{name}_Mainline.toc", "## Interface: 110000\n")
        zf.writestr(f"{name}/Core.lua", "-- new\n")
    return buf.getvalue()


def _install(base: Path, folder: str, name: str, version: str | None) -> Path:
    gv = base / folder
    gv.mkdir(parents=True, exist_ok=True)
    (gv / "Wow.exe").write_bytes(b"")
    addons = gv / "Interface" / "AddOns"
    addons.mkdir(parents=True, exist_ok=True)
    if version is not None:
        d = addons / name
        d.mkdir()
        (d / f"{name}.toc").write_text(f"## Version: {version}\n")
        (d / "Old.lua").write_text("-- old\n")
    return addons


def _svc(base: Path, data: bytes) -> tuple[UpdateService, MagicMock]:
    client = MagicMock()
    client.download = AsyncMock(return_value=data)
    detector = SimpleNamespace(installs=[SimpleNamespace(path=str(base))])
    return UpdateService(client, detector), client


REL = {"addon": "TradeSkillMaster", "channel": "release", "version": "v4.15.4", "url": "u"}


def test_split_suffix():
    assert split_suffix("TradeSkillMaster") == ("TradeSkillMaster", "_retail_")
    assert split_suffix("TradeSkillMaster_AppHelper-Forever") == (
        "TradeSkillMaster_AppHelper",
        "_forever_",
    )
    assert split_suffix("TradeSkillMaster-Progression") == ("TradeSkillMaster", "_classic_")


@pytest.mark.asyncio
async def test_one_download_updates_every_game_version(tmp_path):
    retail = _install(tmp_path, "_retail_", "TradeSkillMaster", "4.14.0")
    forever = _install(tmp_path, "_forever_", "TradeSkillMaster", "v4.15.0")
    svc, client = _svc(tmp_path, _zip("TradeSkillMaster", "v4.15.4"))
    assert await svc.check_and_update([REL]) == ["TradeSkillMaster"]
    client.download.assert_awaited_once_with("u")
    for addons in (retail, forever):
        d = addons / "TradeSkillMaster"
        assert (d / "Core.lua").exists()
        assert not (d / "Old.lua").exists()


@pytest.mark.asyncio
async def test_matching_version_ignores_leading_v(tmp_path):
    _install(tmp_path, "_retail_", "TradeSkillMaster", "4.15.4")
    svc, client = _svc(tmp_path, b"")
    assert await svc.check_and_update([REL]) == []
    client.download.assert_not_awaited()


@pytest.mark.asyncio
async def test_not_installed_dev_and_git_copies_are_left_alone(tmp_path):
    _install(tmp_path, "_retail_", "TradeSkillMaster", None)
    _install(tmp_path, "_classic_", "TradeSkillMaster", "@project-version@")
    era = _install(tmp_path, "_classic_era_", "TradeSkillMaster", "4.0")
    (era / "TradeSkillMaster" / ".git").mkdir()
    svc, client = _svc(tmp_path, _zip("TradeSkillMaster", "v4.15.4"))
    assert await svc.check_and_update([REL]) == []
    client.download.assert_not_awaited()
    assert (era / "TradeSkillMaster" / "Old.lua").exists()


@pytest.mark.asyncio
async def test_manual_install_into_a_new_game_version(tmp_path):
    gv = tmp_path / "_forever_"
    gv.mkdir()
    (gv / "WowClassic.exe").write_bytes(b"")
    svc, _ = _svc(tmp_path, _zip("TradeSkillMaster", "v4.15.4"))
    svc.set_releases([REL])
    assert await svc.install_or_update_addon("TradeSkillMaster-Forever")
    assert (gv / "Interface" / "AddOns" / "TradeSkillMaster" / "Core.lua").exists()


@pytest.mark.asyncio
async def test_bad_zip_installs_nothing(tmp_path):
    addons = _install(tmp_path, "_retail_", "TradeSkillMaster", "4.0")
    svc, _ = _svc(tmp_path, b"not a zip")
    assert await svc.check_and_update([REL]) == []
    assert (addons / "TradeSkillMaster" / "Old.lua").exists()
