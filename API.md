# TradeSkillMaster API Reference

Reverse-engineered from `AppAPI.pyc` and `MainThread.pyc` shipped with the original
Windows TSM Desktop App. All information here was derived by reading the decompiled
bytecode; nothing was obtained from official documentation.

---

## Base URLs

| Purpose                           | URL                                                                        |
| --------------------------------- | -------------------------------------------------------------------------- |
| Authentication (Keycloak OIDC)    | `https://id.tradeskillmaster.com/realms/app/protocol/openid-connect/token` |
| App server (auth + all API calls) | `http://app-server.tradeskillmaster.com/v2/`                               |
| Endpoint-specific subdomains      | `http://{subdomain}.tradeskillmaster.com/v2/`                              |
| CDN data blobs                    | Variable URLs returned by the status endpoint                              |

After a successful login the server returns a map of `endpointSubdomains`; subsequent
calls are routed to the subdomain assigned to each endpoint.

---

## Authentication

Authentication is a two-step process.

### Step 1 - Keycloak OIDC token

```
POST https://id.tradeskillmaster.com/realms/app/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded
```

Form body:

| Field          | Value                       |
| -------------- | --------------------------- |
| `username`     | User's TSM account e-mail   |
| `password`     | User's TSM account password |
| `client_id`    | `legacy-desktop-app`        |
| `grant_type`   | `password`                  |
| `code`         | _(empty string)_            |
| `redirect_uri` | _(empty string)_            |
| `scope`        | `openid`                    |

**Important:** Must be sent as `application/x-www-form-urlencoded`. Keycloak rejects
`multipart/form-data` with HTTP 401.

Response (JSON):

```json
{
  "access_token": "<jwt>",
  "token_type": "Bearer",
  "expires_in": 300,
  "scope": "openid"
}
```

### Step 2 - TSM session exchange

Exchange the OIDC access token for a TSM session token and user info.

```
POST http://app-server.tradeskillmaster.com/v2/auth
Content-Type: application/json
```

Query parameters: see [Request Authentication](#request-authentication) below.

Request body:

```json
{ "token": "<access_token from step 1>" }
```

Response:

```json
{
  "session": "<session_token>",
  "userId": 123456,
  "isPremium": true,
  "endpointSubdomains": {
    "status": "app-server",
    "addon": "app-server",
    "realms2": "app-server"
  }
}
```

The `session` token must be included in all subsequent requests. The
`endpointSubdomains` map tells the client which subdomain to call for each endpoint.

---

## Request Authentication

Every API call (except the OIDC step) includes these query parameters:

| Parameter     | Type   | Description                           |
| ------------- | ------ | ------------------------------------- |
| `session`     | string | Session token from the auth exchange  |
| `version`     | int    | App version integer (`41402`)         |
| `time`        | int    | Current Unix timestamp (seconds)      |
| `token`       | string | HMAC token - see below                |
| `channel`     | string | _(optional)_ `"release"` or `"beta"`  |
| `tsm_version` | string | _(optional)_ TSM addon version string |

### HMAC token computation

```python
import time
from hashlib import sha256

APP_VERSION = 41402
HMAC_SECRET = "3FB1CC5EDC5B43F21CB8ACC23B42B703"

t = int(time.time())
raw = f"{APP_VERSION}:{t}:{HMAC_SECRET}"
token = sha256(raw.encode("utf-8")).hexdigest()
```

The secret is the same for all clients. Token validity is verified server-side by
checking that `time` is within a reasonable window of the server clock.

---

## Request Format

All API requests (except OIDC and raw CDN downloads) follow the same pattern:

- **GET** when there is no body.
- **POST** when a body is present.
- JSON bodies are compressed with gzip and sent with `Content-Encoding: gzip`.
- `User-Agent` header: `TSMApplication/41402`
- SSL verification is disabled in the original app (`verify=False`); the server
  uses plain HTTP for all non-OIDC endpoints.

The response `Content-Type` determines how the response is parsed:

| Content-Type                                   | Parsing               |
| ---------------------------------------------- | --------------------- |
| `application/json`                             | Decoded as JSON       |
| `application/zip` / `application/octet-stream` | Returned as raw bytes |
| anything else                                  | Decoded as UTF-8 text |

Failed requests with HTTP 5xx are retried up to 3 times with exponential back-off
(2 s, 4 s). HTTP 4xx errors are raised immediately without retry.

---

## Endpoints

### `GET /v2/status`

Fetch the current status including realm lists, download URLs, addon versions, and
an optional broadcast message.

Query params: standard auth params + optional `channel` and `tsm_version`.

Response structure:

```json
{
  "appVersion": 41402,
  "addons": [{ "name": "TradeSkillMaster", "version_str": "4.13.5" }],
  "addonMessage": { "id": 0, "msg": "" },
  "realms": [ ... ],
  "regions": [ ... ],
  "realms-Progression": [ ... ],
  "regions-Progression": [ ... ],
  "extraClassicRealms": [ ... ],
  "extraClassicRegions": [ ... ],
  "extraAnniversaryRealms": [ ... ],
  "extraAnniversaryRegions": [ ... ]
}
```

All array values are `RealmEntry[]`. See the game version mapping table below for
which key corresponds to which WoW version.

**RealmEntry** (realm or region object):

```json
{
  "id": 1234,
  "name": "Tarren Mill",
  "region": "EU",
  "appDataStrings": {
    "AUCTIONDB_NON_COMMODITY_DATA": {
      "url": "https://cdn.tradeskillmaster.com/...",
      "lastModified": 1710000000
    },
    "AUCTIONDB_REGION_STAT": {
      "url": "https://cdn.tradeskillmaster.com/...",
      "lastModified": 1710000000
    }
    // ... more tags
  }
}
```

Region entries use the same structure but `name` contains the region identifier
(e.g. `"EU"`, `"US"`) and `region` may be absent.

**Game version mapping:**

| Status key                                           | WoW directory   | API `game_version` |
| ---------------------------------------------------- | --------------- | ------------------ |
| `realms` / `regions`                                 | `_retail_`      | `retail`           |
| `realms-Progression` / `regions-Progression`         | `_classic_`     | `bcc`              |
| `extraClassicRealms` / `extraClassicRegions`         | `_classic_era_` | `classic`          |
| `extraAnniversaryRealms` / `extraAnniversaryRegions` | `_anniversary_` | `anniversary`      |

Display name transform for Progression realms: `BCC-EU` becomes `Progression-EU`.

---

### `GET /v2/addon/{name}`

Download an addon zip file.

| Parameter     | Description                          |
| ------------- | ------------------------------------ |
| `name`        | Addon name, e.g. `TradeSkillMaster`  |
| `channel`     | _(optional)_ `"release"` or `"beta"` |
| `tsm_version` | _(optional)_ Current addon version   |

Response: `application/zip` - raw bytes of the zip archive.

---

### `GET /v2/realms2/list`

List all realms registered to the authenticated user's account.

Response:

```json
{
  "retail": [ ... ],
  "bcc": [ ... ]
}
```

Both arrays contain `RealmEntry[]`.

---

### `GET /v2/realms2/add/{game_version}/{realm_id}`

Register a realm to the user's account.

| Parameter      | Description                               |
| -------------- | ----------------------------------------- |
| `game_version` | `retail`, `bcc`, `classic`, `anniversary` |
| `realm_id`     | Integer realm ID                          |

Response: confirmation object (structure varies).

---

### `GET /v2/realms2/remove/{game_version}/{region}/{realm}`

Remove a realm from the user's account.

| Parameter      | Description                               |
| -------------- | ----------------------------------------- |
| `game_version` | `retail`, `bcc`, `classic`, `anniversary` |
| `region`       | Region string, e.g. `EU`                  |
| `realm`        | Realm name slug, e.g. `Tarren Mill`       |

Response: confirmation object (structure varies).

---

## AppData Download Flow

This is the core data sync flow, equivalent to what `MainThread.pyc` does on a
regular interval.

```
1. GET /v2/status
       |
       v
2. For each game version where TSM_AppHelper is installed:
       |
       v
3. For each realm/region in the status response:
   a. Read local AppData.lua to get stored lastModified per tag
   b. Compare with lastModified values in appDataStrings
   c. If remote lastModified > local: add to pending downloads
       |
       v
4. For each pending (tag, realm) pair:
   - Download blob from appDataStrings[tag].url (CDN, no auth required)
   - If blob starts with gzip magic bytes (0x1f 0x8b): decompress
   - Otherwise: decode as UTF-8
   - Check that response is not an HTML error page
       |
       v
5. Write all downloaded blobs into AppData.lua using LoadData() format
6. Save snapshot to local SQLite cache
```

### AppData.lua format

Each data blob is written as a Lua `LoadData()` call:

```lua
select(2, ...).LoadData("TAG","RealmOrRegion",[[return {downloadTime=N,...}]])
```

The data blob received from the CDN is the verbatim content of the Lua expression
inside `[[...]]`. The `downloadTime` field within the blob is the `lastModified`
timestamp from the API.

---

## AppData Tags

Tags observed in real `AppData.lua` files:

| Tag                                  | Scope      | Description                                         |
| ------------------------------------ | ---------- | --------------------------------------------------- |
| `APP_INFO`                           | Global     | App version, last sync timestamp, broadcast message |
| `AUCTIONDB_NON_COMMODITY_DATA`       | Per-realm  | Current item prices (non-commodity auctions)        |
| `AUCTIONDB_NON_COMMODITY_HISTORICAL` | Per-realm  | Historical price data                               |
| `AUCTIONDB_NON_COMMODITY_SCAN_STAT`  | Per-realm  | Scan statistics                                     |
| `AUCTIONDB_COMMODITY_DATA`           | Per-region | Commodity (stackable) item prices                   |
| `AUCTIONDB_COMMODITY_HISTORICAL`     | Per-region | Commodity historical prices                         |
| `AUCTIONDB_COMMODITY_SCAN_STAT`      | Per-region | Commodity scan statistics                           |
| `AUCTIONDB_REGION_STAT`              | Per-region | Region-wide item statistics                         |
| `AUCTIONDB_REGION_SALE`              | Per-region | Region-wide sale data                               |
| `AUCTIONDB_REGION_HISTORICAL`        | Per-region | Region-wide historical data                         |

The key tags used for staleness detection:

- **Realm data:** `AUCTIONDB_NON_COMMODITY_DATA` - `lastModified` is used as the
  realm's "last updated" display timestamp.
- **Region data:** `AUCTIONDB_REGION_STAT` - same purpose for region rows.

---

## Scheduled Jobs

The original app runs these jobs on a timer:

| Job                | Interval         | Description                               |
| ------------------ | ---------------- | ----------------------------------------- |
| Auction data sync  | Every 60 minutes | Full status + download cycle              |
| Auth token refresh | Every 25 minutes | Re-exchanges OIDC token to extend session |
| WoW install scan   | Every 5 minutes  | Detects new/removed WoW installs          |
| Addon update check | Every 6 hours    | Checks `addons` list from status response |

---

## Known Limitations and Observations

- **No HTTPS for API calls.** All `/v2/` calls use plain HTTP. Only the OIDC step
  uses HTTPS.
- **Shared HMAC secret.** The secret `3FB1CC5EDC5B43F21CB8ACC23B42B703` is
  hardcoded in the distributed app binary and is the same for all users.
- **Session tokens are short-lived.** The auth refresh job runs every 25 minutes,
  suggesting session tokens expire around 30 minutes.
- **CDN URLs require no authentication.** The blob download URLs returned by the
  status endpoint are public CDN URLs and can be fetched without any credentials.
- **AppHelper detection is required.** If `TSM_AppHelper/AppData.lua` is not found
  in a WoW install directory, the server's realm list is still fetched but no data
  is written. The UI shows no realms.
- **Gzip handling is dual-path.** The aiohttp client auto-decompresses
  `Content-Encoding: gzip`, but the CDN sometimes returns raw gzip bytes without
  the header. The client checks the magic bytes (`\x1f\x8b`) and decompresses
  manually if needed.
- **HTML error detection.** The client checks whether the downloaded blob contains
  `<html>` and discards it if so, treating it as an error response from an
  intermediate proxy.
- **`realms2` and `auth` always use `app-server`.** These endpoints are not
  remapped by `endpointSubdomains`; the subdomain is hardcoded in the client.
