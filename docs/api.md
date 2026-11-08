# TradeSkillMaster API Reference

The backend as the official TSM Desktop App 1.0.9 (Electron AppImage) talks to
it. Endpoints and URLs were read from the decompiled client; every response
shape below was captured live on 2026-11-08 unless noted otherwise. User ids in
the examples are replaced by placeholders and presigned URL signatures are
shortened.

This replaced the old HMAC-signed `app-server.tradeskillmaster.com/v2/*` API,
which this app used up to 1.1.16. That API is documented in the git history
(`git show b5cf222:docs/api.md`).

---

## Hosts

| Host | Purpose |
|------|---------|
| `id.tradeskillmaster.com` | Keycloak, realm `app`: login and tokens |
| `realm-api.tradeskillmaster.com` | Realm and region catalogue |
| `desktop-backend.tradeskillmaster.com` | Game versions, the account's followed realms |
| `addon-version.tradeskillmaster.com` | Release channels the account may use |
| `app-backend-sockets.tradeskillmaster.com` | Socket.IO push channel: auction data, addon releases, news |
| `tradeskillmaster.nyc3.digitaloceanspaces.com` | AuctionDB blobs (presigned URLs from socket events) |
| `tradeskillmaster.nyc3.cdn.digitaloceanspaces.com` | Addon zips (public URLs from the `addon` event) |

The official client also has `.dev` variants of every host for its staging
build, and uses desktop-backend for features this app does not implement
(`/backups`, `/sv-snapshots`, `/local-machine-name`, app updates).

Everything is HTTPS with a valid certificate.

---

## Authentication (`tsm/api/oidc.py`)

OIDC authorization code flow with PKCE in the system browser. The
`desktop-app` client refuses the password grant ("Client not allowed for direct
access grants"), so there is no way to log in without a browser.

| Setting | Value |
|---------|-------|
| Endpoint base | `https://id.tradeskillmaster.com/realms/app/protocol/openid-connect` |
| Client id | `desktop-app` (public, no secret) |
| Scope | `openid roles profile email tsm-profile offline_access` |
| Redirect | `http://localhost:<ephemeral port>/auth/callback` |

Keycloak accepts any port on `localhost` with exactly that path. `127.0.0.1`
and other paths are rejected (probed 2026-11-08). The redirect is served by a
one-shot local aiohttp server; the login gives up after 10 minutes.

### Step 1: authorize (browser)

```
GET {base}/auth?client_id=desktop-app
               &response_type=code
               &response_mode=query
               &scope=openid roles profile email tsm-profile offline_access
               &redirect_uri=http://localhost:<port>/auth/callback
               &state=<random>
               &code_challenge=<base64url(sha256(verifier))>
               &code_challenge_method=S256
```

Keycloak redirects the browser to
`/auth/callback?state=<state>&code=<code>&session_state=...`, or with
`error` / `error_description` when the user cancels.

### Step 2: token exchange

```
POST {base}/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
client_id=desktop-app
code=<code>
redirect_uri=<same redirect_uri as step 1>
code_verifier=<verifier>
```

Response (standard Keycloak token response):

```json
{
  "access_token": "<jwt>",
  "expires_in": 604800,
  "refresh_expires_in": 0,
  "refresh_token": "<jwt>",
  "token_type": "Bearer",
  "id_token": "<jwt>",
  "not-before-policy": 0,
  "session_state": "<uuid>",
  "scope": "openid offline_access profile email tsm-profile"
}
```

- `offline_access` makes `refresh_token` an **offline** token
  (`refresh_expires_in: 0`, it does not expire with the browser session). It is
  stored in the keyring under `refresh:<username>`; nothing else is persisted.
- The access token lived 7 days in the capture (`exp - iat = 604800`). The app
  uses `exp` from the token, falling back to `expires_in`, and refreshes
  90 s before expiry, like the official client.
- Errors come back as `{"error": "invalid_grant", "error_description": "..."}`
  with HTTP 400/401.

### Refresh

```
POST {base}/token
grant_type=refresh_token&client_id=desktop-app&refresh_token=<token>
```

Same response shape. A response without `refresh_token` keeps the previous
one. `invalid_grant` means the token was revoked or the session ended; the user
has to sign in again.

### Logout

```
POST {base}/revoke
client_id=desktop-app&token=<refresh token>&token_type_hint=refresh_token
```

Best effort with a 5 s timeout; the answer is ignored.

### Access token claims

Decoded payload of a free account's access token (personal claims omitted):

```json
{
  "sub": "<user uuid>",
  "preferred_username": "<name>",
  "azp": "desktop-app",
  "aud": ["app-app-backend-sockets", "app-realm", "app-pricing", "app-addon-version", "account"],
  "scope": "openid offline_access profile email tsm-profile",
  "realm_access": {
    "roles": ["offline_access", "member", "uma_authorization", "default-roles-app"]
  },
  "resource_access": {
    "app-app-backend-sockets": { "roles": ["socket/accessor"] },
    "app-realm": { "roles": ["auction-houses/accessor", "realms/accessor", "regions/accessor"] },
    "app-pricing": { "roles": ["great-deals/accessor", "auction-house-prices/accessor"] },
    "app-addon-version": { "roles": ["channel/release"] },
    "account": { "roles": ["manage-account", "manage-account-links", "delete-account", "view-profile"] }
  },
  "iat": 1794128540,
  "exp": 1794733340
}
```

Claims the app reads:

| Claim | Use |
|-------|-----|
| `sub` | User id; the `userId` of every user-realms call |
| `preferred_username` (then `email`, `name`) | Display name, keyring key |
| `realm_access.roles` | `premium-platinum` / `premium-gold` decide the tier |
| `resource_access["app-addon-version"].roles` | `channel/<name>`: addon release channels the account may use; `channel/release` always |

Followed realm limit per tier: platinum unlimited, gold 25, free 10.

---

## REST requests (`tsm/api/client.py`)

Every request carries `Authorization: Bearer <access token>` and a
`User-Agent`. Bodies are plain JSON (no gzip). JSON responses are recognised by
`Content-Type: application/json`; anything else is returned as text.

5xx, 408 and 429 are retried up to 3 times (2 s, 4 s, or `Retry-After` when
longer). Other 4xx fail at once with `TSMApiError`.

### Error envelope

The services are NestJS; an error has the HTTP status and this body:

```json
{ "message": "Forbidden resource", "error": "Forbidden", "statusCode": 403 }
```

`message` becomes `TSMApiError.message`. Unlike the old API, a failure is never
an HTTP 200.

### List envelope

realm-api and user-realms wrap lists in `items` plus `metadata`. game-versions
and channels return a bare array.

```json
{ "metadata": { "totalItems": 768 }, "items": [ ... ] }
```

`GET /user-realms` adds paging fields to `metadata`
(`{"totalItems": 2, "page": 1, "pageSize": 2, "totalPages": 1}`). Every list
came back complete in one page, so the app does not page.

---

### `GET realm-api /v2/realms`

The full realm catalogue, not the account's realms: 768 realms across all
game versions and regions (2026-11-08). The app caches it in SQLite so the
realm tab works offline.

```json
{
  "metadata": { "totalItems": 768 },
  "items": [
    {
      "realmId": 2,
      "regionId": 1,
      "connectedRealmId": 4,
      "name": "Winterhoof",
      "slug": "winterhoof",
      "localizedName": "Winterhoof",
      "locale": "en_US",
      "auctionHouses": [
        { "auctionHouseId": 1, "type": "All", "lastModified": 1794126156 }
      ],
      "region": {
        "regionId": 1,
        "name": "North America",
        "regionPrefix": "us",
        "gmtOffset": -8,
        "gameVersion": "Retail",
        "lastModified": 1794127918,
        "gameType": "retail",
        "gameVersionType": "retail"
      }
    }
  ]
}
```

| Field | Notes |
|-------|-------|
| `realmId` | Integer, the id user-realms and socket events use |
| `regionId` | Same as `region.regionId` |
| `connectedRealmId` | Realms sharing it share one auction house |
| `name` | English name (`Aman'Thul`) |
| `localizedName` | Name in the realm's locale (`Aman'thul`, `Der Abyssische Rat`). **This is the AppData.lua key**, as in the official writer |
| `slug`, `locale` | Not used by the app |
| `auctionHouses` | One entry per auction house; see below. Typed as nullable in the app |
| `region` | The full region object, same shape as `/v2/regions` |

`auctionHouses[].type` is `All`, `Alliance` or `Horde` (capitalised; the
user-realms and socket side use upper case). Retail realms have exactly one
`All` house; every classic flavour has an `Alliance` and a `Horde` house:

| gameVersion | Realms | Houses per realm |
|-------------|--------|------------------|
| Retail | 558 | 1 (`All`) |
| Classic Era | 93 | 2 |
| Wrath | 71 | 2 |
| Season of Discovery | 20 | 2 |
| Forever | 12 | 2 |
| Classic Era - Hardcore | 9 | 2 |
| Classic Era - Fresh | 5 | 2 |

`auctionHouseId` is shared by connected realms (Thorium Brotherhood and
Farstriders both carry house 5). It is the number in the blob URLs and the
`ahId` in the AppData.lua meta comment. `lastModified` is usually a Unix
timestamp, but some classic houses report small numbers (`918780`); the app
does not rely on it and takes freshness from the socket events instead.

---

### `GET realm-api /v2/regions`

28 regions: 4 (`us`, `eu`, `tw`, `kr`) for each of 7 game versions.

```json
{
  "metadata": { "totalItems": 28 },
  "items": [
    {
      "regionId": 2,
      "name": "Europe",
      "regionPrefix": "eu",
      "gmtOffset": 0,
      "gameVersion": "Retail",
      "lastModified": 1794099204,
      "gameType": "retail",
      "gameVersionType": "retail"
    }
  ]
}
```

`gameVersion` decides the client folder and the AppData region key prefix
(`tsm/wow/game_versions.py:REGION_GAME_VERSIONS`):

| regionId (us, eu, tw, kr) | gameVersion | gameType | gameVersionType | Folder | Region key |
|---------------------------|-------------|----------|-----------------|--------|------------|
| 1, 2, 3, 4 | Retail | `retail` | `retail` | `_retail_` | `EU` |
| 5, 6, 7, 8 | Classic Era | `classic` | `classic` | `_classic_era_` | `Classic-EU` |
| 13, 14, 15, 16 | Wrath | `classic-progression` | `classic-progression` | `_classic_` | `BCC-EU` |
| 17, 18, 19, 20 | Classic Era - Hardcore | `classic` | `classic-hardcore` | `_classic_era_` | `HC-EU` |
| 21, 22, 23, 24 | Season of Discovery | `classic` | `classic-season-of-discovery` | `_classic_era_` | `SoD-EU` |
| 25, 26, 27, 28 | Classic Era - Fresh | `classic` | `classic-fresh` | `_anniversary_` | `Fresh-EU` |
| 29, 30, 31, 32 | Forever | `forever` | `forever` | `_forever_` | `Forever-EU` |

Notes:

- `gameVersion` is a display string and lags behind the game: the
  `_classic_` progression client is "Wrath" here while desktop-backend labels
  it "Mists of Pandaria". The key stays `BCC-` for compatibility with the
  addon.
- Three region families share `_classic_era_`; the key prefix keeps them apart
  in one AppData.lua. Matching on the two-letter code alone would merge them.
- `name` is the long region name (`Europe`); the key is built from
  `regionPrefix` upper-cased.

---

### `GET desktop-backend /game-versions`

Display labels per client folder. Bare array:

```json
[
  { "gameType": "classic", "label": "Classic Era", "folder": "_classic_era_" },
  { "gameType": "anniversary", "label": "Anniversary", "folder": "_anniversary_" },
  { "gameType": "forever", "label": "Forever", "folder": "_forever_" },
  { "gameType": "classic-progression", "label": "Mists of Pandaria", "folder": "_classic_" },
  { "gameType": "retail", "label": "Retail", "folder": "_retail_" }
]
```

`gameType` here is per folder, not per region: `anniversary` exists only in
this list, the regions call those realms `classic` / `classic-fresh`.

---

### `GET desktop-backend /user-realms?userIds=<sub>`

The realms the account follows. The list is stored server-side and shared with
the official app; these are the realms the socket pushes data for.

```json
{
  "items": [
    {
      "id": "usr_rlm_01m6crcyy6qpc8h826y6wsptzt",
      "userId": "<sub>",
      "realmId": 300,
      "auctionHouseType": "ALL"
    },
    {
      "id": "usr_rlm_01m6crcyy69x57txpgjaqrewgq",
      "userId": "<sub>",
      "realmId": 706,
      "auctionHouseType": "HORDE"
    }
  ],
  "metadata": { "totalItems": 2, "page": 1, "pageSize": 2, "totalPages": 1 }
}
```

| Field | Notes |
|-------|-------|
| `id` | String id (`usr_rlm_...`), needed to delete the entry |
| `realmId` | `realmId` from `/v2/realms` |
| `auctionHouseType` | `ALL`, `ALLIANCE` or `HORDE`: which of the realm's houses. A classic realm followed for both factions is two entries |

In the example, 300 is Tarren Mill (Retail EU, house 97) and 706 is Everlook
(Wrath EU, Horde house 362).

### `POST desktop-backend /user-realms`

```json
{ "realmId": 706, "userId": "<sub>", "auctionHouseType": "HORDE" }
```

`auctionHouseType` must be upper case. The response body is not used by either
client and was not captured; the app reloads the list afterwards. The server
enforces the tier limit; the app checks it first to give a clear message.

### `DELETE desktop-backend /user-realms/<id>`

`<id>` is the `usr_rlm_...` string. Response body unused.

---

### `GET addon-version /channels`

Labels for the addon release channels the account may use. Bare array
`[{"name": "beta", "label": "Beta"}]` (shape from the decompiled client; a
success response has not been captured). Accounts with no extra channels get
the 403 envelope:

```json
{ "message": "Forbidden resource", "error": "Forbidden", "statusCode": 403 }
```

The app treats 403 as "release only". Which channels exist comes from the
`channel/<name>` token roles; this call only supplies labels.

---

## Socket (`tsm/api/socket.py`)

Socket.IO v4 (Engine.IO 4) over a websocket. The app implements the packets it
needs directly on aiohttp, without a socket.io dependency.

```
wss://app-backend-sockets.tradeskillmaster.com/socket.io/?EIO=4&transport=websocket
Authorization: <access token>
```

The `Authorization` header is the **raw** access token, without `Bearer `.

### Handshake and framing

```
server  0{"sid":"GlmzGQ9gnKucO1TaFWuo","upgrades":[],"pingInterval":25000,"pingTimeout":20000,"maxPayload":1000000}
client  40                          join namespace "/"
server  40{"sid":"Rym4e9LIEU6_VKzgFWuq"}
server  2                           ping, every pingInterval
client  3                           pong
server  42["realm_auctiondb",{...}] event: name, then arguments
server  41                          kicked from the namespace
server  44{"message":"..."}         connect refused (bad or expired token)
```

The first digit is the Engine.IO packet type (0 open, 2 ping, 3 pong,
4 message), the second the Socket.IO type (0 connect, 1 disconnect, 2 event,
4 connect error). Every event carries exactly one argument object.

After joining, the server pushes the current state for every followed realm
and its regions (a burst of about 20 events for 2 realms), then `addon` and
`app_info`, and after that pushes again whenever something changes.

### Events

| Event | Sent for | Handled |
|-------|----------|---------|
| `realm_auctiondb` | Per followed auction house, per realm data string | Download + AppData |
| `realm_shopping` | Same payload as `realm_auctiondb` | Same as `realm_auctiondb` |
| `region_auctiondb` | Per region of a followed realm, per region data string | Download + AppData |
| `addon` | Latest addon releases | Addon updater |
| `app_info` | News and the broadcast message | APP_INFO |
| `app_update` | New desktop app release (no payload used) | Ignored (official client schedules an update check) |

#### `realm_auctiondb` / `realm_shopping`

```json
{
  "realmId": 300,
  "auctionHouseType": "ALL",
  "stringType": "AUCTIONDB_NON_COMMODITY_DATA",
  "lastModified": 1794126113,
  "url": "https://tradeskillmaster.nyc3.digitaloceanspaces.com/pricing/nonCommodityAuctionDb/auctionHouse_97_1794126113_gzip.txt?X-Amz-Expires=7200&X-Amz-Signature=..."
}
```

#### `region_auctiondb`

```json
{
  "regionId": 2,
  "stringType": "AUCTIONDB_REGION_STAT",
  "lastModified": "1794099204",
  "url": "https://tradeskillmaster.nyc3.digitaloceanspaces.com/pricing/regionStatDb/region_2_1794099204_gzip.txt?X-Amz-Expires=7200&X-Amz-Signature=..."
}
```

- `lastModified` arrives as a number **or** a numeric string, even within one
  burst. It is the time the addon gets as `downloadTime`.
- `auctionHouseType` is upper case and matches the user-realm entry.
- `url` is a presigned S3 (DigitalOcean Spaces) URL valid for 2 hours
  (`X-Amz-Expires=7200`). It must be fetched **without** an Authorization
  header. A 404 means the blob was superseded by newer data; the next event
  brings the new URL.
- The object path is `pricing/<db>/auctionHouse_<auctionHouseId>_<lastModified>_gzip.txt`
  or `pricing/<db>/region_<regionId>_<lastModified>_gzip.txt`.

### String types

| stringType | Event | Scope | Path segment | Retail | Classic flavours |
|------------|-------|-------|--------------|--------|------------------|
| `AUCTIONDB_NON_COMMODITY_DATA` | realm | Auction house | `nonCommodityAuctionDb` | yes | yes |
| `AUCTIONDB_NON_COMMODITY_SCAN_STAT` | realm | Auction house | `nonCommodityScanStatDb` | yes | yes |
| `AUCTIONDB_NON_COMMODITY_HISTORICAL` | realm | Auction house | `nonCommodityDailyDb` | yes | yes |
| `AUCTIONDB_COMMODITY_DATA` | region | Region | `commodityAuctionDb` | yes | no |
| `AUCTIONDB_COMMODITY_SCAN_STAT` | region | Region | `commodityScanStatDb` | yes | no |
| `AUCTIONDB_COMMODITY_HISTORICAL` | region | Region | `commodityDailyDb` | yes | yes |
| `AUCTIONDB_REGION_STAT` | region | Region | `regionStatDb` | yes | yes |
| `AUCTIONDB_REGION_SALE` | region | Region | `regionSaleDb` | yes | yes |
| `AUCTIONDB_REGION_HISTORICAL` | region | Region | `regionHistoricalDb` | yes | yes |

Captured for a retail EU realm plus a Wrath EU realm: 6 events for retail
region 2, 4 for Wrath region 14 (no commodity data or scan stat), 3 per
followed auction house. `realm_shopping` was not seen in the capture; the
official client routes it through the same handler as `realm_auctiondb`.
The app accepts any `stringType` and writes it under that tag.

`AUCTIONDB_NON_COMMODITY_DATA` (realms) and `AUCTIONDB_REGION_STAT` (regions)
drive the "last updated" column in the realm tab.

### Blob format

The object is stored gzipped without a `Content-Encoding` header, so the client
has to check for the gzip magic (`1f 8b`) and decompress itself
(`TSMApiClient.download`). The content is the Lua table that goes into
AppData.lua, optionally prefixed with `return `:

```lua
{downloadTime=1794098097,fields={"itemString","historical"},data={{25,A8PC0CV},{35,TPLB5K},...}}
```

`fields` names the columns of each `data` row; values are base-32 encoded. The
app strips a leading `return `, and refuses blobs that do not start with `{` or
that contain `]]` (it would end the `[[...]]` string in AppData.lua).

Downloads are retried on 408, 429, 5xx and network errors, 6 attempts with the
delay doubling from 1 s up to 30 s, at most four at a time.

#### `addon`

```json
{
  "isComplete": true,
  "data": [
    {
      "addon": "TradeSkillMaster",
      "channel": "release",
      "version": "v4.15.4",
      "url": "https://tradeskillmaster.nyc3.cdn.digitaloceanspaces.com/addon-versions/TradeSkillMaster-v4.15.4.zip"
    },
    {
      "addon": "TradeSkillMaster_AppHelper",
      "channel": "release",
      "version": "v4.15",
      "url": "https://tradeskillmaster.nyc3.cdn.digitaloceanspaces.com/addon-versions/TradeSkillMaster_AppHelper-v4.15.zip"
    }
  ]
}
```

- One entry per addon and channel the account may use. Accounts with beta
  access get a second entry per addon with `"channel": "beta"`.
- There are no per-game-version packages any more: each zip holds one addon
  folder with a toc per client (`TradeSkillMaster.toc`,
  `TradeSkillMaster_Classic.toc`, ...) and is installed unchanged into every
  game version that already has the addon.
- `url` is a public CDN URL, no auth.
- `version` has a leading `v`; versions are compared without it.
- `isComplete` is passed through by the official client; the app ignores it.

#### `app_info`

```json
{
  "message": { "id": 0, "msg": "" },
  "news": [
    {
      "title": "TSM 4.15 brings WoW: Forever Support, plus New Desktop app",
      "content": "We're pleased to announce that version 4.15 of the TradeSkillMaster addon is now available [...]",
      "timestamp": 1793577133,
      "link": "https://tradeskillmaster.com/news/tsm-4-15-brings-wow-forever-support-plus-new-desktop-app-1180"
    }
  ]
}
```

`message` is the in-game broadcast (`id` 0 and empty `msg` when there is none).
Both are written into the `APP_INFO` blob as they are.

### Reconnects

5 s doubling to 60 s after a dropped connection; 5 s doubling to 300 s with
jitter after the server disconnects us (`41`/`44`, usually an expired or
rejected token). A token refresh while disconnected reconnects at once.

---

## AppData.lua

Written to `<WoW>/<folder>/Interface/AddOns/TradeSkillMaster_AppHelper/AppData.lua`,
but only for game versions where TradeSkillMaster or the AppHelper is installed.
The official 1.0.9 client writes this format; the addon reads it on login.

```lua
select(2, ...).LoadData("APP_INFO","Global",[[return {version="1.0.9",lastSync=1794128540,message={id=0,msg=""},news={...}}]]) --<APP_INFO,Global,1794128540>
select(2, ...).LoadData("AUCTIONDB_NON_COMMODITY_DATA","Tarren Mill",[[return {downloadTime=1794126113,...}]]) --<AUCTIONDB_NON_COMMODITY_DATA,Tarren Mill,1794126113,97>
for _,r in ipairs({"Thorium Brotherhood","Farstriders"}) do select(2, ...).LoadData("AUCTIONDB_NON_COMMODITY_DATA",r,[[return {...}]]) end --<AUCTIONDB_NON_COMMODITY_DATA,Thorium Brotherhood|Farstriders,1794126157,5>
select(2, ...).LoadData("AUCTIONDB_REGION_STAT","EU",[[return {downloadTime=1794099204,...}]]) --<AUCTIONDB_REGION_STAT,EU,1794099204>
```

- The trailing comment is the meta the writer reads back:
  `<TYPE,Key[|Key...],lastModified[,auctionHouseId]>`. `lastModified` decides
  whether a newer socket event needs a download.
- Realm keys: `localizedName`, plus `-Horde` / `-Alliance` for a faction
  auction house (`Everlook-Horde`). Connected realms share one auction house
  and are written as one ipairs line.
- Region keys: see the regions table. `APP_INFO` uses `Global`.
- Lines the parser does not recognise are kept verbatim.
- Writes are debounced (1.5 s) and batched per file; entries for realms the
  account no longer follows are removed.
- `APP_INFO` (`{version, lastSync, message, news}`) is rewritten every 15
  minutes and on every `app_info` event. `version` is the official client
  version the addon expects (`OFFICIAL_APP_VERSION` in `tsm/app.py`).

---

## Addon updates

The `addon` event lists the latest release per addon and channel. Each release
is one zip with a toc per client, installed unchanged into every game version
that already has the addon. Installs that are git checkouts, or whose toc reads
`@project-version@`, are left alone.

---

## Differences from the old API

| Old (`app-server /v2`, up to 1.1.16) | New |
|--------------------------------------|-----|
| Password grant, `legacy-desktop-app` client | PKCE browser login, `desktop-app` client |
| Session token from `/v2/auth`, lived about 10 minutes | Keycloak access token, refreshed with an offline refresh token |
| HMAC query parameters, plain HTTP | Bearer header, HTTPS |
| `endpointSubdomains` per session | Fixed hosts |
| Errors as HTTP 200 `{"success": false}` | HTTP status + NestJS error body |
| Poll `/v2/status` every hour | Socket pushes changes |
| Realms registered via `/v2/realms2/add` | `/user-realms`, shared with the official app |
| One addon zip per game version (`-Classic`, `-Progression`, ...) | One multi-toc zip per addon |
| Region strings `BCC-EU`, `Classic-EU` in the status payload | Built by the client from `gameVersion` + `regionPrefix` |
