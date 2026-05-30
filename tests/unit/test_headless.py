"""Tests for headless execution module."""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tsm.headless import run_headless


@pytest.mark.asyncio
@patch("tsm.headless.ConfigStore")
@patch("tsm.headless.Database")
@patch("tsm.headless.TSMApiClient")
@patch("tsm.headless.AuthService")
async def test_headless_wow_path_update(
    mock_auth_svc_cls, mock_api_client_cls, mock_db_cls, mock_config_store_cls
):
    # Setup mocks
    mock_config_store = MagicMock()
    mock_config_store_cls.return_value = mock_config_store
    mock_cfg = MagicMock()
    mock_config_store.load.return_value = mock_cfg
    mock_cfg.model_copy.return_value = mock_cfg

    # Run with just wow-path
    args = argparse.Namespace(
        wow_path="/path/to/wow",
        login=False,
        sync=False,
        backup=False,
        install_addons=False,
        skip_detection=True,
    )

    await run_headless(args)

    mock_cfg.model_copy.assert_called_once_with(update={"wow_path": "/path/to/wow"})
    mock_config_store.save.assert_called_once_with(mock_cfg)


@pytest.mark.asyncio
@patch("tsm.headless.ConfigStore")
@patch("tsm.headless.Database")
@patch("tsm.headless.TSMApiClient")
@patch("tsm.headless.AuthService")
@patch("tsm.headless.webbrowser.open")
@patch("tsm.headless.getpass.getpass")
@patch("builtins.input")
async def test_headless_login_signup_and_auth(
    mock_input,
    mock_getpass,
    mock_webbrowser_open,
    mock_auth_svc_cls,
    mock_api_client_cls,
    mock_db_cls,
    mock_config_store_cls,
):
    # Setup mocks
    mock_auth_svc = MagicMock()
    mock_auth_svc_cls.return_value = mock_auth_svc
    mock_auth_svc.login = AsyncMock()

    mock_db = MagicMock()
    mock_db.connect = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db_cls.return_value = mock_db

    mock_api_client = MagicMock()
    mock_api_client.close = AsyncMock()
    mock_api_client_cls.return_value = mock_api_client

    # Inputs:
    # 1. Option '2' (Sign up)
    # 2. Press Enter to proceed to login
    # 3. Email: 'test@example.com'
    mock_input.side_effect = ["2", "", "test@example.com"]
    mock_getpass.return_value = "secretpass"

    args = argparse.Namespace(
        wow_path=None,
        login=True,
        sync=False,
        backup=False,
        install_addons=False,
        skip_detection=True,
    )

    await run_headless(args)

    mock_webbrowser_open.assert_called_once_with("https://www.tradeskillmaster.com/")
    mock_auth_svc.login.assert_called_once_with("test@example.com", "secretpass", remember_me=True)
    mock_db.connect.assert_called_once()
    mock_db.close.assert_called_once()
    mock_api_client.close.assert_called_once()


@pytest.mark.asyncio
@patch("tsm.headless.ConfigStore")
@patch("tsm.headless.Database")
@patch("tsm.headless.TSMApiClient")
@patch("tsm.headless.AuthService")
@patch("tsm.headless.WoWDetectorService")
@patch("tsm.headless.AddonWriterService")
@patch("tsm.headless.AuctionDataService")
@patch("tsm.headless.UpdateService")
@patch("tsm.headless.BackupService")
async def test_headless_sync_and_backup(
    mock_backup_svc_cls,
    mock_update_svc_cls,
    mock_auction_svc_cls,
    mock_addon_writer_cls,
    mock_detector_cls,
    mock_auth_svc_cls,
    mock_api_client_cls,
    mock_db_cls,
    mock_config_store_cls,
):
    # Setup mock configs
    mock_config_store = MagicMock()
    mock_config_store_cls.return_value = mock_config_store
    mock_cfg = MagicMock(
        wow_path="/valid/wow/path", backup_period_minutes=60, backup_retain_days=30
    )
    mock_config_store.load.return_value = mock_cfg

    mock_db = MagicMock()
    mock_db.connect = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db_cls.return_value = mock_db

    mock_api_client = MagicMock()
    mock_api_client.close = AsyncMock()
    mock_api_client_cls.return_value = mock_api_client

    # Setup auth restore
    mock_auth_svc = MagicMock()
    mock_auth_svc_cls.return_value = mock_auth_svc
    mock_auth_svc.restore_session = AsyncMock(return_value=True)

    # Setup sync and updater mocks
    mock_auction_svc = MagicMock()
    mock_auction_svc_cls.return_value = mock_auction_svc
    mock_data = MagicMock(addon_versions=[{"name": "TradeSkillMaster", "version_str": "1.0.0"}])
    mock_auction_svc.refresh_all_realms = AsyncMock(return_value=mock_data)

    mock_update_svc = MagicMock()
    mock_update_svc_cls.return_value = mock_update_svc
    mock_update_svc.check_and_update = AsyncMock(return_value=["TradeSkillMaster"])

    # Setup backup mock
    mock_backup_svc = MagicMock()
    mock_backup_svc_cls.return_value = mock_backup_svc
    mock_backup_svc.run = MagicMock(return_value=["/backup/path.zip"])

    # Run headless sync and backup
    args = argparse.Namespace(
        wow_path=None,
        login=False,
        sync=True,
        backup=True,
        install_addons=False,
        skip_detection=True,
    )

    await run_headless(args)

    mock_auth_svc.restore_session.assert_called_once()
    mock_auction_svc.refresh_all_realms.assert_called_once()
    mock_update_svc.check_and_update.assert_called_once()
    mock_backup_svc.run.assert_called_once_with(60, 30)
    mock_db.connect.assert_called_once()
    mock_db.close.assert_called_once()
    mock_api_client.close.assert_called_once()


@pytest.mark.asyncio
@patch("tsm.headless.ConfigStore")
@patch("tsm.headless.Database")
@patch("tsm.headless.TSMApiClient")
@patch("tsm.headless.AuthService")
@patch("tsm.headless.WoWDetectorService")
@patch("tsm.headless.UpdateService")
@patch("tsm.headless.installed_versions")
async def test_headless_install_addons(
    mock_installed_versions,
    mock_update_svc_cls,
    mock_detector_cls,
    mock_auth_svc_cls,
    mock_api_client_cls,
    mock_db_cls,
    mock_config_store_cls,
):
    # Setup mock configs
    mock_config_store = MagicMock()
    mock_config_store_cls.return_value = mock_config_store
    mock_cfg = MagicMock(wow_path="/valid/wow/path")
    mock_config_store.load.return_value = mock_cfg

    mock_db = MagicMock()
    mock_db.connect = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db_cls.return_value = mock_db

    mock_api_client = MagicMock()
    mock_api_client.close = AsyncMock()
    mock_api_client.status.get = AsyncMock(
        return_value={
            "addons": [
                {"name": "TradeSkillMaster", "version_str": "4.14.2"},
                {"name": "TradeSkillMaster_AppHelper", "version_str": "4.14.2"},
            ]
        }
    )
    mock_api_client_cls.return_value = mock_api_client

    # Setup auth restore
    mock_auth_svc = MagicMock()
    mock_auth_svc_cls.return_value = mock_auth_svc
    mock_auth_svc.restore_session = AsyncMock(return_value=True)

    # Setup detector installs mock
    mock_detector = MagicMock()
    mock_detector.installs = [MagicMock(path="/valid/wow/path")]
    mock_detector_cls.return_value = mock_detector

    # Setup installed_versions mock
    mock_installed_versions.return_value = ["_retail_"]

    # Setup update service mock
    mock_update_svc = MagicMock()
    mock_update_svc_cls.return_value = mock_update_svc
    mock_update_svc.install_or_update_addon = AsyncMock(return_value=True)

    # Run headless install addons
    args = argparse.Namespace(
        wow_path=None,
        login=False,
        sync=False,
        backup=False,
        install_addons=True,
        skip_detection=True,
    )

    await run_headless(args)

    mock_auth_svc.restore_session.assert_called_once()
    mock_api_client.status.get.assert_called_once()
    mock_installed_versions.assert_called_once()
    assert mock_update_svc.install_or_update_addon.call_count == 2
    mock_db.connect.assert_called_once()
    mock_db.close.assert_called_once()
    mock_api_client.close.assert_called_once()

