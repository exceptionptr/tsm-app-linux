# Changelog

All notable changes to tsm-app-linux are documented here.

---

## [1.0.4] - 2026-03-19

### Fixed
- Last Updated column in the Realm Data tab now correctly shows the primary tag
  timestamp (AUCTIONDB_NON_COMMODITY_DATA for realms, AUCTIONDB_REGION_STAT for
  regions). Previously, when secondary tags were downloaded but the primary tag
  was unchanged, a max() fallback wrote a wrong timestamp into the snapshot;
  this caused the column to show the wrong time until the next manual refresh.
- Tray notification text trimmed to "{n} realm(s)/region(s) updated."

### Added
- Reverse-engineered TSM API reference document (API.md) covering auth flow,
  all endpoints, AppData download flow, tags, and scheduled job intervals.

### CI
- softprops/action-gh-release bumped to v2.3.2 (Node.js 24 compatible)
- AUR publishing extracted from release.yml into a separate aur.yml workflow
  triggered manually via workflow_dispatch

---

## [1.0.3] - 2026-03-18

### Fixed
- Realm list no longer clears when WoW install or AppHelper is not detected
  during a refresh; existing rows are kept with reset status labels
- Closing via tray Quit no longer shows a double confirmation dialog
- Config no longer silently mutated when quitting via tray

### Added
- Timestamps on all log output
- Log file with rotation at ~/.local/share/tsm-app/logs/tsm-app.log,
  retaining the last 5 backups

### Chore
- Removed em-dashes from source comments and strings
- Cleaned up PKGBUILD comments

---

## [1.0.2] - 2026-03-18

### Fixed
- CI workflows now only trigger on the main branch
- Reverted softprops/action-gh-release to v2 to fix GitHub Release upload crash

---

## [1.0.1] - 2026-03-18

### Fixed
- Closing window with confirmation now quits the app instead of hiding to tray
- Prevent multiple simultaneous instances; second launch shows "already running"
  dialog instead of opening a second window
- APScheduler 4.x (AsyncScheduler) bundled correctly for Arch; the system
  package is 3.x which is not compatible
- App icon now installed to the hicolor theme so it appears in desktop launchers

### CI
- GitHub Actions bumped to Node.js 24 runtime

---

## [1.0.0] - 2026-03-17

Initial release.
