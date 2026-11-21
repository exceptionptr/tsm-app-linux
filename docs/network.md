# Network Traffic Analysis

What the official TSM Desktop App (Electron AppImage, 1.0.11 captured first,
1.0.14 analysed later) and this app send
over the network, to which hosts, and how the two differ on the wire. The
protocol itself (payloads, events, auth) is in `docs/api.md`; this page covers
who talks to whom, when, and what a client looks like to the server.

The first capture (version 1.0.11) was made 2026-11-14 with mitmproxy in local capture mode on Linux, with the
official client trusting the mitmproxy CA. Headers, methods, paths and bodies
were recorded; tokens and cookies were redacted by the capture script. The
session was short (start, click through every tab, add one realm), so
long-running behaviour (hourly timers, large data bursts, error paths) is not
covered. Items marked "unverified" come from reading the decompiled client or
from the code of this app, not from the capture.

---

## Hosts and addresses

All TSM hostnames resolve to the same Cloudflare anycast addresses, so the IP
alone does not tell the services apart; the TLS SNI and `Host` header do.

| Host | Addresses (2026-11-14) | Fronted by |
|------|------------------------|------------|
| `id`, `realm-api`, `desktop-backend`, `addon-version`, `app-backend-sockets` (all `.tradeskillmaster.com`) | `104.26.10.228`, `104.26.11.228`, `172.67.70.56`, `2606:4700:20::681a:ae4`, `2606:4700:20::681a:be4`, `2606:4700:20::ac43:4638` | Cloudflare |
| `tradeskillmaster.nyc3.digitaloceanspaces.com` (AuctionDB blobs) | `162.243.189.2` | DigitalOcean Spaces, no CDN |
| `tradeskillmaster.nyc3.cdn.digitaloceanspaces.com` (addon zips) | `104.18.42.227`, `172.64.145.29` (plus IPv6) | Cloudflare |

The official client used IPv6 where available. Every REST connection was
closed again right after its response.

---

## Official client 1.0.14: what changed since 1.0.11

Version 1.0.14 was analysed from its bundles and from further captures and
debug output. This app follows it (see `docs/api.md`, "Client identity per
channel"). Differences from the 1.0.11 notes below:

- Keycloak calls come from Chromium (`TradeSkillMaster/1.0.14 ... Electron/44.4.3`
  User-Agent) and carry client hints, `Sec-Fetch-*`, `Accept-Language: en-US`
  and `Accept-Encoding: gzip, deflate, br, zstd`, but no `Origin`. Token
  revoke goes out through undici (`node`), without `Authorization`.
- Authorize has a `nonce` and a fixed parameter order; `redirect_uri` is
  `http://localhost/auth/callback` without port.
- The refresh token is rotated on every refresh.
- AuctionDB blobs come from `pricing-data.tradeskillmaster.com` with a single
  `verify` query parameter, no `X-Amz-*`, no auth, no `Range`.
- The socket polls first (`t` timestamp parameter, `sid` after open, `40`
  POST), then upgrades to a websocket; the server answers the initial burst on
  polling, in one body with several packets. The connect reply carries a `pid`.
- undici requests carry `Accept-Encoding: br, gzip, deflate` (not
  `gzip, deflate`) plus the Sentry trace headers.

The sections up to "This app" describe the 1.0.11 capture and are kept as
recorded.

## Official client 1.0.11 on the wire

### Processes and fingerprints

| Origin | User-Agent | Notes |
|--------|------------|-------|
| Main process, REST (`/local-machine-name`) | `node` | Fetch API (undici). Adds `sentry-trace` and `baggage` headers (`sentry-release=1.0.11`, `sentry-environment=production`). |
| Utility worker, REST (everything else) | `node-fetch` | Header names in lower case, order: `accept: */*`, `accept-encoding: gzip, deflate, br`, `authorization`, `user-agent`, `host`, `connection: keep-alive`. POST adds `content-length` and `content-type: application/json` before `user-agent`. |
| Main process, Socket.IO polling | `node-XMLHttpRequest` | Header order: `User-Agent`, `Accept: */*`, `Authorization`, `Host`, `Connection: close` (the official client sends it; we do not and reuse one keep-alive connection for the polling phase, a known difference). POST adds `Content-type: text/plain;charset=UTF-8` and `Content-Length`. |
| Main process, websocket upgrade | none | `Authorization`, `Sec-WebSocket-Version`, `Sec-WebSocket-Key`, `Connection`, `Upgrade`, `Sec-WebSocket-Extensions: permessage-deflate; client_max_window_bits`, `Host`. |

The `Authorization` header is `Bearer <token>` on REST and the raw token on the
socket, as in `docs/api.md`.

### Socket sequence

The official client does not open a websocket directly. It follows the default
socket.io-client transport order:

1. `GET /socket.io/?EIO=4&transport=polling&t=<id>` (Engine.IO open, gets the sid)
2. `POST ...&sid=<sid>` with body `40` (join namespace)
3. `GET ...&sid=<sid>` (long poll, the first events arrive here)
4. `GET ...&transport=websocket&sid=<sid>` with `Upgrade: websocket` (101)
5. Probe and upgrade frames, then one more polling GET to flush, then
   websocket only (ping every 25 s)

### REST calls seen

Startup, within about 1.5 s of the login being restored:

| Order | Request | Notes |
|-------|---------|-------|
| 1 | `GET desktop-backend /game-versions` | Sent twice |
| 2 | `GET desktop-backend /user-realms?userIds=<sub>` | Seen three times in the session |
| 3 | `POST desktop-backend /group-sends/claim` | Body `{"gameTypes":["forever","retail"]}`, the game versions found on disk. Response was 2 bytes (an empty list, unverified). Meaning of "group sends" is unverified. |

On UI actions:

| Trigger | Request |
|---------|---------|
| Open Backups or Data Export | `GET desktop-backend /local-machine-name?systemIds=` (empty list, 75 byte answer) |
| Add Realm dialog, confirm | `POST desktop-backend /user-realms` with `{"realmId":<n>,"userId":"<sub>","auctionHouseType":"ALL"}` (201), then the list again |

Not seen in this capture, but in the decompiled client: `/backups`,
`/sv-snapshots`, app update checks, `GET realm-api /v2/realms` and
`/v2/regions` (cached, so not repeated), `GET addon-version /channels`, and the
Sentry error reporting host (no error occurred, so nothing was sent).

### What is sent about the machine

Everything the capture showed is: the account's user id (`sub`) as a query or
body field, the realm ids, the installed game version names, and the access
token. No hardware id, no file list, no paths, no character names and no
addon contents left the machine in this session. `/local-machine-name` is a
read: it asks the server for a stored display name of a system, and the
`systemIds` list was empty.

That capture only covers startup and the UI actions above. The official client
sends more on other triggers, see the next section.

### What the official client uploads (SavedVariables)

Evidence: `~/.config/tradeskillmaster/logs/main.log` of the official client
(entries "Uploading snapshot for ..." and "Snapshot uploaded successfully for
.../WTF/Account/<account folder>/SavedVariables/TradeSkillMaster.lua"), the
worker scripts in `resources/assets/scripts-dist/` of the AppImage, and TSM's
privacy policy ("TSM addon data uploaded by the Desktop App").

| Worker | Trigger | Input |
|--------|---------|-------|
| `uploadSnapshotProcess.js` | App start (all game versions and accounts with a `TradeSkillMaster.lua`) and when the file changes | `wowPath`, WoW account folder name, game version, game type, access token, `systemId` (device id) |
| `watchWowDBProcess.js` | Always, while logged in | Watches the SavedVariables folders of every game version and account |
| `uploadBackupProcess.js` | After a local backup, Premium only | The backup patch file of the SavedVariables |

What the uploaded data contains, per the policy and the addon source
(`TradeSkillMasterDB`, `TradeSkillMaster_AppHelperDB`):

- WoW account folder name, character names, realms, factions, guilds
- gold balances and history, ledger of sales, purchases, income and expenses
  (can include names of other players traded with)
- professions, groups, operations, TSM settings
- auction house scans with the scanning character, Black Market scan
- addon error reports and addon usage events (analytics)

Snapshot upload on the wire (captured with a proxy, official 1.0.14, after a
game reload):

| Step | Request |
|------|---------|
| 1 | `POST desktop-backend /sv-snapshots/uploads` (empty body, bearer token): answer `{"id":"<uuid>","url":"<presigned PUT url>"}` (201), URL valid 2 h on the `tsm-desktop-sv-snapshots-production` bucket, path `<userId>/<id>` |
| 2 | `PUT <presigned url>`: gzip body, about 139 KB (about 860 KB as JSON) |
| 3 | `POST desktop-backend /sv-snapshots` with `{"id":"<uuid>"}` (202), confirms the upload |

The JSON in the body has the keys `account` (WoW account folder name),
`gameType`, `tsmDB` (the whole `TradeSkillMasterDB`, about 270 keys, scoped
keys such as `c@<character> - <realm>@...`, `g@`, `s@`, `f@`, `r@`, `p@`),
`appHelperDB` (`blackMarket`, `region`, `errorReports`, `analytics`,
`fullScan`, `groupImports`), `saveAge` and `systemId`. Character names appear
in the keys and in the values. Mind the proxy set-up: the node workers only go
through the proxy with `NODE_USE_ENV_PROXY=1`; the socket and the pricing blob
downloads did not show up in that capture.

This app sends none of it. It only reads the SavedVariables locally (backups,
accounting export, realm names) and never uploads them, so no account folder
name and no character name leaves the machine.

Name resolution: during the capture the process also issued mDNS (UDP 5353)
and LLMNR (UDP 5355) multicast queries on the local link. Their origin
(presumably the Chromium network stack) was not examined.

---

## This app (2.2.1) on the wire

| Destination | When | What |
|-------------|------|------|
| `id.tradeskillmaster.com` | Login (embedded window), token refresh 90 s before expiry, logout | OIDC PKCE, see `docs/api.md` |
| `realm-api.tradeskillmaster.com` | Realm tab refresh | `/v2/realms`, `/v2/regions`, cached in SQLite |
| `desktop-backend.tradeskillmaster.com` | Start, realm tab, every socket connect | `/game-versions`, `/user-realms` (GET, POST, DELETE), `/group-sends/claim`, the version feed (`/app-updates/release/latest-linux.yml`) |
| `addon-version.tradeskillmaster.com` | Start | `/channels` |
| `app-backend-sockets.tradeskillmaster.com` | Start, reconnect | Polling session, then websocket upgrade |
| `pricing-data.tradeskillmaster.com` | Per socket event | Blob download with the `verify` URL, no auth header |
| `tradeskillmaster.nyc3.cdn.digitaloceanspaces.com` | Addon update | Public zip download |
| `api.github.com` | Once at start | Latest release tag of this project, no auth |
| `nether.wowhead.com`, `wow.zamimg.com` | When item names or icons are shown | Item id in the URL, cached on disk |

Differences from the official client that a server can observe:

| Aspect | Official 1.0.14 | This app |
|--------|-----------------|----------|
| REST `User-Agent` | `node-fetch` (worker), `node` (undici) | the same, per channel |
| Keycloak `User-Agent` | Chromium `TradeSkillMaster/<version> ...` | the same on login window, token and refresh (live version); `node` on revoke |
| Authorize and token `redirect_uri` | `http://localhost/auth/callback` | the same, caught in the embedded login window |
| Header names and order | per library (node-fetch, undici, Chromium) | the same, set by `OrderedRequest` (websocket order read from the bundle, not seen on the wire) |
| TLS fingerprint | Node / Chromium | Python OpenSSL (TLS 1.2 minimum, ALPN as the official channel), cipher list not matched |
| `accept-encoding` | `gzip, deflate, br` (node-fetch), `br, gzip, deflate` (undici), `gzip, deflate, br, zstd` (Chromium) | the same without `zstd`, and without `br` when brotli is not installed |
| Chromium client hints (`sec-ch-ua*`, `priority`) | sent on Keycloak token calls | sent on token and refresh (aiohttp, captured order); the login window sends its own, `sec-ch-ua` rewritten |
| `Origin`, `cookie` on token calls | none, none | none, none |
| Socket transport | polling, then upgrade | polling, then upgrade |
| Socket `User-Agent` | `node-XMLHttpRequest` (polling), none (websocket) | `node-XMLHttpRequest` (polling), `node-fetch` (websocket default) |
| Websocket `permessage-deflate` | offered | offered |
| Sentry `sentry-trace`, `baggage` | sent | never sent (deliberate) |
| Keycloak logout | revoke, logout page in the window | revoke, logout URL in a hidden window, then the login window opens again |
| Extra calls | `/group-sends/claim`, `/local-machine-name`, version feed, Sentry | `/group-sends/claim`, version feed; no `/local-machine-name`, no Sentry |
| `app_info.version` written to AppData | the official version | the live version from the update feed (1.0.14 fallback) |

---

## Findings relevant to the sync outage of 2026-11

- The official client and this app receive the same events for the same
  account: `addon` and `app_info` arrive, no `realm_auctiondb`,
  `realm_shopping` or `region_auctiondb`. The outage is on the server side and
  tied to accounts; other users report that a new account receives data again.
- AppData timestamps are identical in both clients, so the data is not just
  withheld from this app.
- Hypothesis, contradicted on 2026-11-20: the server may push realm data only for
  accounts that have uploaded a SavedVariables snapshot recently. This fits the
  advice to close WoW and the app, restart the app, then start WoW, because the
  upload happens at app start and on file changes. Against it: the official
  client uploaded snapshots during the outage and still received no
  `realm_auctiondb`. Test: capture the official client (proxy) around a game
  reload and check whether the upload is followed by realm events.
  Result: the official client logged in, uploaded a snapshot after a reload
  and was still not served. The addon status tooltip about 20 minutes later
  read "App Synced 19 Min Ago", "AuctionDB Realm Data is 7 Hr 29 Min Old",
  "AuctionDB Region Data is 22 Hr 30 Min Old". So the upload does not trigger
  the push; the outage stays on the server side.

---

## Notes for a compatible server

A server that the unmodified client can talk to has to provide, per the
traffic above:

- OIDC: the Keycloak endpoints of `docs/api.md` (authorize, token, revoke) and
  a JWT whose claims match the "Access token claims" table.
- REST: `GET /game-versions`, `GET /user-realms`, `POST /user-realms`,
  `DELETE /user-realms/<id>`, `GET /v2/realms`, `GET /v2/regions`,
  `GET /channels`, and, for the official client, `POST /group-sends/claim`
  and `GET /local-machine-name`.
- Socket.IO v4 with both transports (polling and websocket, upgrade probe),
  the raw token in `Authorization`, and the six events with the payloads in
  `docs/api.md`.
- Object storage for the blobs: any HTTP server returning the gzipped Lua
  table without a `Content-Encoding` header, at URLs the socket events point to.
