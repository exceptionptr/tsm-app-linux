"""App configuration pydantic model."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WoWInstall(BaseModel):
    path: str
    version: str  # "_retail_", "_classic_", "_classic_era_"


class AppConfig(BaseModel):
    wow_installs: list[WoWInstall] = Field(default_factory=list)
    minimize_to_tray: bool = True
    notifications_enabled: bool = True
    notify_realm_data: bool = True
    notify_addon_update: bool = True
    notify_backup: bool = True
    start_minimized: bool = False
    show_confirmation_on_exit: bool = False
    backup_period_minutes: int = 60
    backup_retain_days: int = 30
