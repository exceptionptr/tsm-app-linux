"""Addon info pydantic models."""

from __future__ import annotations

from pydantic import BaseModel


class AddonVersion(BaseModel):
    addon_name: str
    version: str
    download_url: str | None = None
    changelog: str | None = None


class AddonInfo(BaseModel):
    name: str
    installed_version: str | None = None
    latest_version: str | None = None
    last_check: int | None = None  # unix timestamp
    needs_update: bool = False
