"""Headless execution module for running completely in the terminal or via cron."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import sys
import webbrowser
from pathlib import Path

from tsm.api.client import TSMApiClient
from tsm.core.models.config import WoWInstall
from tsm.core.services.addon_writer import AddonWriterService
from tsm.core.services.auction import AuctionDataService
from tsm.core.services.auth import AuthService
from tsm.core.services.backup import BackupService
from tsm.core.services.updater import UpdateService
from tsm.core.services.wow_detector import WoWDetectorService
from tsm.storage.auction_cache import AuctionCache
from tsm.storage.config_store import ConfigStore
from tsm.storage.database import Database
from tsm.wow.utils import installed_versions, normalize_wow_base

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".local" / "share" / "tsm-app"
DB_PATH = DATA_DIR / "data.db"


async def run_headless(args: argparse.Namespace) -> None:
    """Entry point for headless mode."""
    # 1. Config store and update WoW path if requested
    config_store = ConfigStore()
    if args.wow_path:
        cfg = config_store.load()
        cfg = cfg.model_copy(update={"wow_path": args.wow_path})
        config_store.save(cfg)
        print(f"WoW path updated to: {args.wow_path}")
        if not args.login and not args.sync and not args.backup:
            return

    # 2. Setup Database
    db = Database(DB_PATH)
    await db.connect()

    # 3. API and Auth Service
    api_client = TSMApiClient()
    auth_svc = AuthService(api_client)

    try:
        # 4. Handle login/sign-up
        if args.login:
            print("=== TradeSkillMaster Headless Sign-Up & Auth ===")
            print("1. Log in to an existing TSM account")
            print("2. Sign up / Create a new TSM account")
            try:
                choice = input("Select an option (1 or 2, default: 1): ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nOperation cancelled.")
                sys.exit(1)

            if choice == "2":
                signup_url = "https://www.tradeskillmaster.com/"
                print("\nTo sign up, please visit the TSM website:")
                print(f"  {signup_url}\n")
                try:
                    opened = webbrowser.open(signup_url)
                    if opened:
                        print("Opening registration page in your browser...")
                    else:
                        print("Please open the URL in your web browser.")
                except Exception:
                    print("Please open the URL in your web browser.")

                try:
                    input(
                        "\nPress Enter once you have completed registration "
                        "to proceed to login..."
                    )
                except (KeyboardInterrupt, EOFError):
                    print("\nOperation cancelled.")
                    sys.exit(1)

            print("\nPlease enter your TSM credentials:")
            try:
                username = input("Email: ").strip()
                password = getpass.getpass("Password: ")
            except (KeyboardInterrupt, EOFError):
                print("\nOperation cancelled.")
                sys.exit(1)

            if not username or not password:
                print("Error: Email and password are required.")
                sys.exit(1)

            try:
                print("Logging in...")
                await auth_svc.login(username, password, remember_me=True)
                print("Login successful! Credentials stored securely.")
            except Exception as e:
                print(f"Login failed: {e}")
                sys.exit(1)
            return

        # Try to restore session using environment variables first, then stored credentials
        restored = False
        env_email = os.environ.get("TSM_EMAIL")
        env_password = os.environ.get("TSM_PASSWORD")
        if env_email and env_password:
            try:
                print("Authenticating with credentials from environment variables...")
                await auth_svc.login(env_email, env_password, remember_me=False)
                restored = True
            except Exception as e:
                print(f"Authentication failed using environment variables: {e}")

        if not restored:
            restored = await auth_svc.restore_session()

        if not restored:
            print(
                "Error: Not authenticated. Please run with `--login` or set "
                "TSM_EMAIL and TSM_PASSWORD environment variables."
            )
            sys.exit(1)

        if args.install_addons:
            wow_detector = WoWDetectorService(skip_scan=args.skip_detection)
            cfg = config_store.load()
            if cfg.wow_path:
                base = str(normalize_wow_base(Path(cfg.wow_path)))
                if Path(base).is_dir():
                    wow_detector.set_installs([WoWInstall(path=base)])
                    print(f"Using configured WoW path: {base}")

            if not wow_detector.installs and not args.skip_detection:
                print("No WoW path configured. Scanning filesystem for WoW installations...")
                await wow_detector.get_installs()

            if not wow_detector.installs:
                print("Error: No WoW installations detected. Cannot install addons.")
                sys.exit(1)

            updater_svc = UpdateService(api_client, wow_detector)
            print("Fetching latest addon versions from TSM API...")
            status = await api_client.status.get()
            addons_list = status.get("addons", [])

            gv_to_suffix = {
                "_retail_": "",
                "_classic_era_": "-Classic",
                "_classic_": "-Progression",
                "_anniversary_": "-Anniversary",
            }

            base_path = Path(wow_detector.installs[0].path)
            versions = installed_versions(base_path)

            if not versions:
                print("No WoW game versions found under the WoW installation directory.")
            else:
                print(f"Detected game version(s): {', '.join(versions)}")
                for gv in versions:
                    suffix = gv_to_suffix.get(gv, "")
                    for base_name in ("TradeSkillMaster", "TradeSkillMaster_AppHelper"):
                        full_name = base_name + suffix
                        version = next(
                            (a["version_str"] for a in addons_list if a.get("name") == base_name),
                            None,
                        )
                        if version:
                            print(f"Installing {full_name} (v{version}) for {gv}...")
                            success = await updater_svc.install_or_update_addon(full_name, version)
                            if success:
                                print(f"Successfully installed {full_name}.")
                            else:
                                print(f"Failed to install {full_name}.")
                        else:
                            print(f"Addon version not found in API for {full_name}")

        # 5. Handle sync and backup
        # Default behavior (if no action flags are provided): run both sync and backup
        run_sync = args.sync or (
            not args.backup and not args.wow_path and not args.install_addons
        )
        run_backup = args.backup or (
            not args.sync and not args.wow_path and not args.install_addons
        )

        if run_sync:
            cache = AuctionCache(db)
            wow_detector = WoWDetectorService(skip_scan=args.skip_detection)

            # Resolve WoW path from config
            cfg = config_store.load()
            if cfg.wow_path:
                base = str(normalize_wow_base(Path(cfg.wow_path)))
                if Path(base).is_dir():
                    wow_detector.set_installs([WoWInstall(path=base)])
                    print(f"Using configured WoW path: {base}")
                else:
                    print(f"Warning: Configured WoW path does not exist: {base}")

            if not wow_detector.installs and not args.skip_detection:
                print("No WoW path configured. Scanning filesystem for WoW installations...")
                await wow_detector.get_installs()

            if not wow_detector.installs:
                print(
                    "Warning: No WoW installations detected. Auction data and "
                    "addon updates cannot be written."
                )
                print("Please configure your WoW path using `--wow-path <path>`.")

            addon_writer = AddonWriterService(wow_detector)
            auction_svc = AuctionDataService(api_client, cache, addon_writer)
            updater_svc = UpdateService(api_client, wow_detector)

            print("Fetching and synchronizing auction data...")
            data = await auction_svc.refresh_all_realms()
            print("Auction data synchronization completed.")

            addon_versions = getattr(data, "addon_versions", [])
            if addon_versions:
                print("Checking for addon updates...")
                updated = await updater_svc.check_and_update(addon_versions)
                if updated:
                    print(f"TSM addon(s) updated: {', '.join(updated)}")
                else:
                    print("Addons are up to date.")

        if run_backup:
            # Use same wow_detector settings
            wow_detector = WoWDetectorService(skip_scan=args.skip_detection)
            cfg = config_store.load()
            if cfg.wow_path:
                base = str(normalize_wow_base(Path(cfg.wow_path)))
                if Path(base).is_dir():
                    wow_detector.set_installs([WoWInstall(path=base)])

            if not wow_detector.installs and not args.skip_detection:
                await wow_detector.get_installs()

            backup_svc = BackupService(wow_detector)
            print("Starting backup of SavedVariables...")
            loop = asyncio.get_running_loop()
            created = await loop.run_in_executor(
                None,
                lambda: backup_svc.run(
                    cfg.backup_period_minutes,
                    cfg.backup_retain_days,
                ),
            )
            if created:
                print(f"Backup completed. Created {len(created)} backup(s):")
                for path in created:
                    print(f"  - {path}")
            else:
                print("Backup skipped (period not elapsed or no changes detected).")

    finally:
        await api_client.close()
        await db.close()
