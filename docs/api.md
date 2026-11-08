# TradeSkillMaster API Reference

The backend as the official TSM Desktop App 1.0.9 (Electron AppImage) talks to
it, verified live on 2026-11-08. This replaced the old HMAC-signed
`app-server.tradeskillmaster.com/v2/*` API, which this app used up to 1.1.16.

## Hosts

| Host | Purpose |
|------|---------|
| `id.tradeskillmaster.com` | Keycloak, realm `app`: login and tokens |
| `realm-api.tradeskillmaster.com` | Realm and region catalogue |
| `desktop-backend.tradeskillmaster.com` | Game versions, the account's followed realms |
| `addon-version.tradeskillmaster.com` | Release channels the account may use |
| `app-backend-sockets.tradeskillmaster.com` | Socket.IO push channel: auction data, addon releases, news |

Data blobs are downloaded from presigned URLs carried in socket events, without
an Authorization header. They may be gzip compressed; `TSMApiClient.download`
unpacks them.

## Authentication (`tsm/api/oidc.py`)

OIDC authorization code flow with PKCE in the system browser.

- Endpoint base: `https://id.tradeskillmaster.com/realms/app/protocol/openid-connect`
- Client id: `desktop-app` (public, no secret)
- Scope: `openid roles profile email tsm-profile offline_access`
- Redirect: `http://127.0.0.1:<ephemeral port>/auth/callback`, served by a
  one-shot local aiohttp server. The login gives up after 10 minutes.
- `offline_access` yields an offline refresh token. It is stored in the keyring
  (`refresh:<username>`) and survives restarts.
- The access token is refreshed 90 s before it expires. A rejected refresh ends
  the session and the user has to sign in again.
- Logout revokes the refresh token at `/revoke`.

Claims used from the access token: `sub` (user id), `preferred_username`, and
`realm_access.roles` (`premium-platinum`, `premium-gold`, release channel roles).

Followed realm limit per tier: platinum unlimited, gold 25, free 10.

## REST requests (`tsm/api/client.py`)

Every request carries `Authorization: Bearer <access token>`. 5xx, 408 and 429
are retried with backoff (Retry-After is honoured); other 4xx fail at once with
`TSMApiError`.

### `GET realm-api /v2/realms`

`{"items": [Realm]}` with `realmId`, `regionId`, `name`, `localizedName`,
`connectedRealmId`, `auctionHouses: [{auctionHouseId, type, lastModified}]` and
an embedded `region`.

### `GET realm-api /v2/regions`

`{"items": [Region]}` with `regionId`, `name`, `regionPrefix` (`"eu"`) and
`gameVersion`. The `gameVersion` string decides the client folder and the
AppData region key prefix (`tsm/wow/game_versions.py:REGION_GAME_VERSIONS`):

| gameVersion | Folder | Region key |
|-------------|--------|------------|
| Retail | `_retail_` | `EU` |
| Wrath | `_classic_` | `BCC-EU` |
| Classic Era | `_classic_era_` | `Classic-EU` |
| Classic Era - Hardcore | `_classic_era_` | `HC-EU` |
| Season of Discovery | `_classic_era_` | `SoD-EU` |
| Classic Era - Fresh | `_anniversary_` | `Fresh-EU` |
| Forever | `_forever_` | `Forever-EU` |

### `GET desktop-backend /game-versions`

`[{gameType, label, folder}]`: display labels per client folder.

### `GET desktop-backend /user-realms?userIds=<sub>`

`{"items": [{id, userId, realmId, auctionHouseType}]}`. `auctionHouseType` is
`ALL`, `ALLIANCE` or `HORDE`. These are the realms the socket pushes data for.

### `POST desktop-backend /user-realms`

Body `{"realmId": int, "userId": sub, "auctionHouseType": "ALL"}`.

### `DELETE desktop-backend /user-realms/<id>`

### `GET addon-version /channels`

`[{name, label}]`. 403 means the account has no extra channels.

## Socket (`tsm/api/socket.py`)

Socket.IO v4 over a websocket:
`wss://app-backend-sockets.tradeskillmaster.com/socket.io/?EIO=4&transport=websocket`.
The handshake sends the raw access token (no `Bearer `) in the `Authorization`
header. The app implements the few packets it needs directly on aiohttp:

```
server  0{"sid":..,"pingInterval":25000,"pingTimeout":20000}   open
client  40                                                    join "/"
server  40{"sid":..}                                          joined
server  2   client  3                                         ping / pong
server  42["event", payload]                                  event
server  41 / 44{"message":..}                                 kicked / refused
```

After joining, the server pushes the current data for every followed realm, then
pushes again on every change.

| Event | Payload |
|-------|---------|
| `realm_auctiondb`, `realm_shopping` | `{realmId, auctionHouseType, stringType, lastModified, url}` |
| `region_auctiondb` | `{regionId, stringType, lastModified, url}` |
| `addon` | `{data: [{addon, channel, version, url}]}` |
| `app_info` | `{message: {id, msg}, news: [{title, content, timestamp, link}]}` |

`lastModified` arrives as a number or a string.

Reconnects: 5 s doubling to 60 s after a dropped connection, 5 s doubling to
300 s with jitter after the server disconnects us (expired or rejected token).
A token refresh while disconnected reconnects at once.

## AppData.lua

Written to `<WoW>/<folder>/Interface/AddOns/TradeSkillMaster_AppHelper/AppData.lua`,
but only for game versions where TradeSkillMaster or the AppHelper is installed.

```
select(2, ...).LoadData("TYPE","Key",[[return DATA]]) --<TYPE,Key,time,ahId>
for _,r in ipairs({"A","B"}) do select(2, ...).LoadData("TYPE",r,[[return DATA]]) end --<TYPE,A|B,time,ahId>
```

- Realm keys: `localizedName`, plus `-Horde` / `-Alliance` for a faction
  auction house. Connected realms share one auction house and one ipairs line.
- Region keys: see the table above. `APP_INFO` uses `Global`.
- Lines the parser does not recognise are kept verbatim.
- Writes are debounced (1.5 s) and batched per file; entries for realms the
  account no longer follows are removed.
- `APP_INFO` (`{version, lastSync, message, news}`) is rewritten every 15 minutes
  and on every `app_info` event. `version` is the official client version the
  addon expects (`OFFICIAL_APP_VERSION` in `tsm/app.py`).

## Addon updates

The `addon` event lists the latest release per addon and channel. Each release
is one zip with a toc per client, installed unchanged into every game version
that already has the addon. Installs that are git checkouts, or whose toc reads
`@project-version@`, are left alone. Versions are compared without a leading `v`.
