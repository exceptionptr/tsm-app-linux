"""App configuration pydantic model."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class WoWInstall:
    """Represents a single WoW installation base directory.

    path is the WoW root (e.g. /home/user/Games/world-of-warcraft).
    Game-version subdirectories (_retail_, _classic_, etc.) are derived on demand.
    """

    path: str


class AppConfig(BaseModel):
    wow_path: str = ""  # WoW base directory (e.g. /home/user/Games/world-of-warcraft)
    minimize_to_tray: bool = True
    notifications_enabled: bool = True
    notify_realm_data: bool = True
    notify_addon_update: bool = True
    notify_backup: bool = True
    start_minimized: bool = False
    show_confirmation_on_exit: bool = False
    backup_period_minutes: int = 60
    backup_retain_days: int = 30
