# TradeSkillMaster API Reference

The backend as the official TSM Desktop App 1.0.14 (Electron AppImage) talks to
it, and how this app speaks to it. Endpoints and URLs were read from the
decompiled client; response shapes were captured live (first on 2026-11-08, the
request headers again against 1.0.14) unless noted otherwise. User ids in the
examples are replaced by placeholders and download signatures are shortened.
Request headers per channel are described under "Client identity per channel".

This replaced the old HMAC-signed `app-server.tradeskillmaster.com/v2/*` API,
which this app used up to 1.1.16. That API is documented in the git history
(`git show b5cf222:docs/api.md`).

---

## Hosts

| Host | Purpose |
|------|---------|
| `id.tradeskillmaster.com` | Keycloak, realm `app`: login and tokens |
| `realm-api.tradeskillmaster.com` | Realm and region catalogue |
| `desktop-backend.tradeskillmaster.com` | Game versions, the account's followed realms, the app version feed |
| `tsm-desktop-app-builds-production.nyc3.cdn.digitaloceanspaces.com` | Target of the feed redirect (`latest-linux.yml`) |
| `addon-version.tradeskillmaster.com` | Release channels the account may use |
| `app-backend-sockets.tradeskillmaster.com` | Socket.IO push channel: auction data, addon releases, news |
| `pricing-data.tradeskillmaster.com` | AuctionDB blobs (URLs with a `verify` parameter from socket events, behind Cloudflare) |
| `tradeskillmaster.nyc3.cdn.digitaloceanspaces.com` | Addon zips (public URLs from the `addon` event) |

The official client also has `.dev` variants of every host for its staging
build, and uses desktop-backend for features this app does not use
(`/backups`, `/sv-snapshots`, `/local-machine-name`). App updates are used only to read the current version (see "App version feed"). Client
methods exist for `/backups` and `/local-machine-name`, but nothing calls them.

Everything is HTTPS with a valid certificate.

---

## App version feed

The official client reads its version from electron-updater's generic provider:
`GET desktop-backend/app-updates/release/latest-linux.yml?noCache=<Date.now() in base 32>`
answers 302 to the builds CDN (`.../versions/<X.Y.Z>/latest-linux.yml`), whose YAML
starts with `version: X.Y.Z`. Nothing is downloaded.

This app does the same in `tsm/api/app_version.py`:

- Headers in the captured order: `x-user-staging-id`, `authorization: Bearer` only
  while a valid token exists, `user-agent: electron-builder`, `cache-control: no-cache`,
  `sec-fetch-site: none`, `sec-fetch-mode: no-cors`, `sec-fetch-dest: empty`,
  `accept-encoding`, `accept-language: en-US`, `priority`. `Host` comes first.
- `x-user-staging-id` is a UUID v4 stored in `~/.local/share/tsm-app/.updaterId`
  (reused when valid, recreated otherwise), like electron-updater.
- The version is taken 1:1 when it is a plain `X.Y.Z`, with no bound (older ones too).
  An error, a timeout (3 s) or a malformed answer keeps the current value. The built-in
  1.0.14 applies only until the feed has answered in this run.
- Checks at start, on every socket connect and 0 to 300 s after an `app_update` event;
  a check that starts during another is queued once.

Known differences: the official request is Chromium net over HTTP/2, ours is aiohttp
over HTTP/1.1 (the accepted exception). The `priority` value is not recorded in the
capture, `u=4, i` is a guess. The `accept-encoding` drops `br` and `zstd` when aiohttp
cannot decode them.

---

## Client identity per channel

The official 1.0.14 client is an Electron app that sends requests through four
different HTTP stacks, and each one has its own `User-Agent` and header set.
This app copies the set of the stack that sends the same request officially
(`tsm/api/official.py`, `tsm/api/client.py`, `tsm/api/oidc.py`,
`tsm/api/socket.py`).

| Channel | Used for | User-Agent | Other headers |
|---------|----------|------------|---------------|
| aiohttp with the Chromium header set | Keycloak token and refresh | `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) TradeSkillMaster/<live version> Chrome/152.0.7977.130 Electron/44.4.3 Safari/537.36` | In the captured order: `content-length`, `sec-ch-ua-platform: "Linux"`, `user-agent`, `accept: application/json`, `sec-ch-ua`, `content-type: application/x-www-form-urlencoded;charset=UTF-8`, `sec-ch-ua-mobile: ?0`, `sec-fetch-site: cross-site`, `sec-fetch-mode: cors`, `sec-fetch-dest: empty`, `sec-fetch-storage-access: active`, `accept-encoding` (what aiohttp decodes), `accept-language: en-US`, `priority: u=1, i`. No `Origin`, no cookie, no `Authorization`. Not sent from Chromium: see "Authentication" |
| node-fetch | realm-api, game-versions, user-realms, channels, group-sends, backups, addon zip | `node-fetch` | `Accept: */*`, `Accept-Encoding: gzip, deflate, br`, `Authorization: Bearer <token>` (not on the addon zip). POSTs add `Content-Type: application/json`. No `Accept-Language` |
| undici (Node global fetch) | AuctionDB downloads, local-machine-name, Keycloak revoke | `node` | `Accept: */*`, `Accept-Language: *`, `Sec-Fetch-Mode: cors`, `Accept-Encoding: br, gzip, deflate`; `Authorization: Bearer` only on local-machine-name. The official client adds Sentry `sentry-trace` and `baggage` here |
| node-XMLHttpRequest | Socket.IO long polling | `node-XMLHttpRequest` | `Accept: */*`, `Authorization: <raw token>`; the POST adds `Content-Type: text/plain;charset=UTF-8` |
| `ws` | Socket.IO websocket upgrade | none | `Authorization: <raw token>`, `Sec-WebSocket-*`, `permessage-deflate; client_max_window_bits` offered. No `User-Agent`, `Accept` or `Accept-Encoding` |

The Keycloak login page and the logout navigation run in an embedded Chromium
window (QtWebEngine) on a persistent profile under `~/.local/share/tsm-app`, with
the official `User-Agent` (live version), `Accept-Language: en-US` and client
hints. The token and refresh requests go through aiohttp with the Chromium header
set (no `Origin`, no cookie), like the other channels. All of them use
aiohttp with `OrderedRequest` (`tsm/api/http.py`), which sends exactly the headers
its channel builder lists, in the captured order and casing, and adds nothing of
its own:

- undici: `host, connection: keep-alive, [Authorization], [content-type], accept,
  accept-language, sec-fetch-mode, user-agent, accept-encoding, [content-length]`,
  lower case except `Authorization`.
- node-fetch: `Accept, Accept-Encoding, Authorization, [Content-Length,
  Content-Type], User-Agent, Host, Connection: keep-alive`.
- polling: the set above, unchanged (D-001).
- websocket: `Authorization, Sec-WebSocket-Version, Sec-WebSocket-Key, Connection,
  Upgrade, Sec-WebSocket-Extensions, Host`. This order is read from the `ws` code in
  the official bundle (extra headers first, Host added last by Node). It was not
  seen on the wire.

AuctionDB URLs go out byte for byte (`%2B`, `%2F`, `=` in `verify` stay as received).
`tests/unit/test_api_client_headers.py` and `test_socket.py` read `raw_headers` from
a local server to pin all of this.

TLS: node-fetch, the ws library and polling use one SSL context without ALPN, undici
one with `http/1.1` (`tsm/api/http.py`, `ssl_context`); both set TLS 1.2 as the
minimum and verify certificates. The version feed and the Chromium channel are
separate (see below).

The socket probe starts like engine.io-client does it: right after the open packet,
together with the namespace connect (`40`) and before the first long poll, so the
websocket handshake is in flight while the first long poll is open.

---

## Remaining differences from the official client

Measured or read, as stated per line. "Official" is the 1.0.14 AppImage (Electron 44,
Chromium 152).

Deliberate, permanent:

- **Sentry.** The official client adds `sentry-trace` and `baggage` to undici
  requests and sends envelopes to Sentry. This app never sends any of them, never
  reads the DSN and never will. Read from the bundle and the capture.
- **Group sends banner.** The official window shows pending group sends; this app has
  no such UI. New sends raise only the existing tray notification.
- **Version lookup over aiohttp.** The feed request is aiohttp over HTTP/1.1, not
  Chromium net over HTTP/2 (see "App version feed").

QtWebEngine Chromium residual (the login window, token, refresh and logout):

- The engine is the user's QtWebEngine, not Chromium 152. Header values (`User-Agent`,
  `sec-ch-ua`, `Accept-Language`, `sec-ch-ua-mobile`, `sec-ch-ua-platform`,
  `sec-ch-ua-full-version-list`) say 152; `sec-ch-ua` is overwritten in place by the
  request interceptor (measured: one header, Chromium's position). The engine
  underneath is what the package brings, logged at startup with
  `qWebEngineChromiumVersion()`:

  | Package | Chromium base |
  |---------|---------------|
  | venv, AppImage, Nuitka binary (PySide6 6.10 wheel) | 134.0.6998.208 |
  | PySide6 wheels 6.9 to 6.12 | 130 (6.9) to 140 (6.12) |
  | Flatpak (`io.qt.PySide.BaseApp` 6.11) | the base app's QtWebEngine 6.11 |
  | nix (qtwebengine 6.11.2), Arch (6.12) | 140.0.7339.225 and 140.0.7339.264 |
  | deb, rpm | the distribution's or the bundled wheel's, per release |

  No PySide6 in the supported range (`>=6.6.0`) reaches 152, and no new dependency is
  allowed, so this stays. Measured on the venv build (6.10.2); the other rows are
  the version tables of those Qt releases, not measured on a running package.
- JS-visible engine (`navigator.userAgentData.brands`, Blink and V8 features) is the
  real one, and Qt orders brands and the full version list by key (`Chromium` before
  `Not?A_Brand`), the reverse of the capture. The low-entropy `sec-ch-ua` is the only
  hint reordered by the interceptor.
- `sec-ch-ua-platform-version` was sent by Chromium after `Accept-CH` in the test; it
  is unknown whether the official client sends it.
- Token and refresh requests (aiohttp, not Chromium). A fetch from a page of the login
  profile cannot read Keycloak's error answers: a 400 `invalid_grant` carries no
  `Access-Control-Allow-Origin` (measured with curl: successful preflights answer for
  `Origin: file://`, error POSTs have no CORS headers), so the page saw only
  `TypeError: Failed to fetch` and could not tell a rejected token from a network
  error. The requests therefore go through aiohttp with the captured Chromium header
  set. Differences from the official request: no `Cookie` (the Keycloak cookie lives in
  the login profile), no `Origin` (the official one has none either), and the TLS
  ClientHello, HTTP version (HTTP/1.1 instead of HTTP/2) and header casing on the wire
  are aiohttp's and OpenSSL's, not Chromium's. `--disable-web-security` is not used.
  `400 invalid_grant` now means "token rejected, log in again"; network errors, 5xx and
  429 are transient.
- Client hints on navigations. The official navigations (authorize, logout, the login
  form POST) carry no `sec-ch-ua*`; only the token fetch does. QtWebEngine 6.10 sends
  `sec-ch-ua`, `-mobile` and `-platform` on every request whatever the client hints
  settings (`setAllClientHintsEnabled(False)` only drops the high-entropy ones; there
  is no `setIsEnabled`), JS off and `--disable-features=UserAgentClientHint` change
  nothing, and an interceptor can only replace a header (an empty one goes out
  empty), not remove it. Ours therefore carry them on navigations too.
- Login form POST: measured, already equal to the capture (`Origin: null`,
  `Sec-Fetch-Site: same-origin`, also under `Referrer-Policy: no-referrer`).
- Authorize navigation: a direct `QWebEnginePage.load` goes out with `Sec-Fetch-Site: none`
  and `Sec-Fetch-User: ?1`; the capture has `cross-site`, no `Sec-Fetch-User`, no Referer.
  The login window therefore loads a tiny page of its own (`setHtml`, base
  `file:///tsm-login/`, `<meta name="referrer" content="no-referrer">`) whose script does
  `location.replace(authorizeUrl)`. Measured with a script redirect from a cross-site
  page: `cross-site`, `navigate`, `document`, no `Sec-Fetch-User`, no Referer. While the
  hop is open the guard accepts only the `data:text/html` page or the
  `file:///tsm-login/` base for main-frame loads and keeps that state; it ends at the
  https authorize URL, and any other target is blocked and logged. The page needs
  `LocalContentCanAccessRemoteUrls`: without it Qt refuses the script hop from a
  `file:` base with `ERR_NETWORK_ACCESS_DENIED` (seen against the real host). If the
  hop still fails to load, the window loads the URL directly once (old headers; the
  log line names the error).
- Logout navigation: ours goes out with `Sec-Fetch-Site: none` and `Sec-Fetch-User: ?1`;
  the capture has `cross-site` and `?1`. `cross-site` plus `?1` needs a real click on a
  link in a shown view (measured); a click on a hidden view and a synthetic `click()` do
  not navigate or carry no `?1`. Showing the window for it would flash UI, so it is not
  changed: only `Sec-Fetch-Site` differs.
- HTTP/2 SETTINGS, WINDOW_UPDATE, pseudo-header order and QUIC use of the login window
  are Chromium's own and were not compared.

TLS (aiohttp channels):

- ALPN, minimum version and certificate checks are set per channel. The ClientHello
  extension order, supported groups, signature algorithms, cipher list and GREASE come
  from OpenSSL and cannot be set to BoringSSL's from Python's `ssl`; no new dependency is
  allowed. The cipher list was left at OpenSSL's default on purpose: the list the
  official Electron Node offers was not captured, and guessing it would add a difference.
- **JA4 comparison: pending.** It needs the developer's mitmproxy capture of the official
  client (`NODE_EXTRA_CA_CERTS` with the mitmproxy CA for the AppImage) next to a capture
  of this app. No JA4 value is claimed here.

Encodings:

- `br` is advertised only when aiohttp can decode it (`brotli`/`brotlicffi`, not a
  declared dependency), `zstd` only when aiohttp reports it can. Without them the
  `Accept-Encoding` lacks those tokens, unlike the official client's.

Polling:

- **`Connection`.** The bundle suggests the official polling requests send `Connection:
  close` (`agent: false`); ours keep one keep-alive connection (D-001, because `close`
  produced HTTP 400 `Session ID unknown` on the second poll). Pending the developer's
  mitmproxy capture of the official socket; until then no change. Polling header sets
  were never captured on the wire.

Not verified or guessed:

- **Nonce.** The id token's `nonce` is compared with the one sent (payload only, no
  signature check); a mismatch or an unreadable id token ends the login with an error
  and the token is not adopted. `state` is checked too, like keycloak-js.
- `priority: u=4, i` on the version feed request is a guess; the capture has no value.
- `Host` casing and position on the version feed request is unknown.
- `sec-ch-ua-platform-version` (see above), and the websocket header order (read from
  code, not from the wire).
- Real Keycloak login, refresh and logout from each distribution package were not run
  in this review environment; see the ticket notes for what was tested.

---

## Authentication (`tsm/api/oidc.py`)

OIDC authorization code flow with PKCE in an embedded Chromium window
(QtWebEngine, `tsm/ui/login_window.py`), like the official client. The
`desktop-app` client refuses the password grant ("Client not allowed for direct
access grants"), so there is no way to log in without the Keycloak page. There is no
system browser and no loopback listener any more.

The token requests (code exchange, refresh) use their own timeout: 30 s in total,
10 s to connect, so a stuck connect ends in an error and the login page.

| Setting | Value |
|---------|-------|
| Endpoint base | `https://id.tradeskillmaster.com/realms/app/protocol/openid-connect` |
| Client id | `desktop-app` (public, no secret) |
| Scope | `openid roles profile email tsm-profile offline_access` |
| Redirect | `http://localhost/auth/callback` (no port, as the official client) |

The window (600x800, framed, resizable, no menu, background `#1e1e1e`) loads the
authorize URL. A request interceptor catches the redirect to the callback URL before
it reaches the network and reads `code`, `state` and any `error`. Navigations of the
main frame outside `https://id.tradeskillmaster.com` are blocked. Closing the window
cancels the login; the app then shows its login page with one "Login Again" button
and the error text, and quits when that is closed with nobody signed in. The login
gives up after 10 minutes.

Remember me works like the official client: there is no choice of our own. The refresh
token is always stored after a successful login (keyring) and deleted on logout. The
Keycloak "Remember me" checkbox only affects Keycloak's own session cookie in the
window's profile. Without a valid session at startup (no token, or the refresh fails
with `invalid_grant`) the window opens at once.

### Step 1: authorize (login window)

```
GET {base}/auth?client_id=desktop-app
               &redirect_uri=http://localhost/auth/callback
               &state=<uuid>
               &response_mode=query
               &response_type=code
               &scope=openid roles profile email tsm-profile offline_access
               &nonce=<uuid>
               &code_challenge=<base64url(sha256(verifier))>
               &code_challenge_method=S256
```

The parameters are sent in this order, as keycloak-js builds them, and the
scope is encoded with `+` (the logout URL and form bodies keep `%20`). `state` and `nonce` are two independent random
UUIDs. The PKCE verifier is 96 characters from `A-Za-z0-9`; the challenge is the
base64url SHA-256 of it without padding. There is no `prompt`, `kc_idp_hint`,
`ui_locales` or `max_age`.

Keycloak redirects the window to
`/auth/callback?state=<state>&code=<code>&session_state=...`, or with
`error` / `error_description` when the user cancels.

### Step 2: token exchange

```
POST {base}/token
Content-Type: application/x-www-form-urlencoded;charset=UTF-8
Accept: application/json

code=<code>
grant_type=authorization_code
client_id=desktop-app
redirect_uri=<same redirect_uri as step 1>
code_verifier=<verifier>
```

The form keys go in this order. There is no scope, no client secret and no
`Authorization`. The request goes through aiohttp with the Chromium header set of the
keycloak-js fetch, in the captured order (see the channel table), with the live
user agent. It sends no `Origin` and no cookie, and its TLS differs from
Chromium's (see "Remaining differences"). A page fetch was tried and dropped: the
page could not read Keycloak's CORS-less error answers.

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
grant_type=refresh_token&refresh_token=<token>&client_id=desktop-app
```

Sent like the token exchange (aiohttp, Chromium header set), no scope. Same response shape.

**The refresh token rotates.** Every successful refresh returns a new
`refresh_token`; the new value must be stored and used next time (the app
writes it to the keyring when it differs from the stored one). A response
without `refresh_token` keeps the previous one. `invalid_grant` (HTTP 400)
means the token was revoked, replaced or the session ended; the user has to
sign in again. The official client refreshes when less than 90 s of validity
remain, checking every 30 s.

### Logout

```
POST {base}/revoke
client_id=desktop-app&token=<refresh token>&token_type_hint=refresh_token
```

Sent with the undici headers (`User-Agent: node`, content type
`application/x-www-form-urlencoded;charset=UTF-8`, no `Authorization`, no
cookie). Best effort with a 5 s timeout; the answer (200, empty body) is
ignored.

Then, like the official client, a window is sent to the end-session endpoint:

```
GET {base}/logout?client_id=desktop-app
                 &post_logout_redirect_uri=http://localhost/auth/callback
                 &id_token_hint=<id token>
```

Keycloak answers 302 to the redirect URI, which is caught like the login callback
and ends the Keycloak session in the window's profile. This runs in a hidden window
(15 s timeout, skipped without an id token) and the app then shows its login page,
which opens the Keycloak window again with a fresh state, nonce and PKCE. The official
client shows the Keycloak login page in the same window instead; this app adds no UI.

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

Every request carries `Authorization: Bearer <access token>` and the headers of
its channel (node-fetch for the services, undici for local-machine-name; see
"Client identity per channel"). Bodies are plain JSON (no gzip). JSON responses are recognised by
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

Socket.IO v4 (Engine.IO 4). Like the official socket.io-client (transports
`polling`, then `websocket`), the app first opens an HTTP long-polling session
and then upgrades it to a websocket. It implements the packets it needs
directly on aiohttp, without a socket.io dependency.

```
https://app-backend-sockets.tradeskillmaster.com/socket.io/?EIO=4&transport=polling&t=<stamp>
Authorization: <access token>
```

The `Authorization` header is the **raw** access token, without `Bearer `, on
every polling request and on the websocket handshake. There is no auth payload
and no custom query; `t` is a short timestamp token on polling requests, and
the parameter order is `EIO`, `transport`, `t`, `sid`. The 1.0.14 client's
`appVersion` configuration value is never sent.

### Handshake, upgrade and framing

```
client  GET  ...&transport=polling&t=<stamp>             (no sid yet)
server  0{"sid":"GlmzGQ9gnKucO1TaFWuo","upgrades":["websocket"],"pingInterval":25000,"pingTimeout":20000,"maxPayload":1000000}
client  websocket ...&transport=websocket&sid=<sid>      probe starts here, in parallel with the next two lines
client  POST ...&sid=<sid>  body 40                      join namespace "/"
client  GET  ...&sid=<sid>                               long poll
server  40{"sid":"Rym4e9LIEU6_VKzgFWuq","pid":"..."}     the Socket.IO id differs from the Engine.IO sid
client  2probe     server 3probe                         probe; polling is paused
client  5                                                upgrade, all traffic now on the websocket
server  2                           ping, every pingInterval
client  3                           pong
server  42["realm_auctiondb",{...}] event: name, then arguments
server  41                          kicked from the namespace
server  44{"message":"..."}         connect refused (bad or expired token)
```

A polling body can hold several packets separated by the 0x1e record separator;
the initial push for all followed realms usually arrives that way, before the
upgrade finishes (about 0.7 s after the first request). The server pings, the
client answers; an idle connection is dropped after `pingInterval +
pingTimeout` (45 s). If the server offers no upgrade, or the websocket fails,
the app stays on polling. The upgrade packets `2probe`, `3probe` and `5` are
Engine.IO types (2 ping, 3 pong, 5 upgrade) with a text body.

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
| `app_update` | New desktop app release (no payload used) | Schedules a version feed check 0 to 300 s later, at most one pending, like the official client |
| `group_send` | A group was sent to this account | Claims group sends (see "Group sends") |

#### `realm_auctiondb` / `realm_shopping`

```json
{
  "realmId": 300,
  "auctionHouseType": "ALL",
  "stringType": "AUCTIONDB_NON_COMMODITY_DATA",
  "lastModified": 1794126113,
  "url": "https://pricing-data.tradeskillmaster.com/pricing/nonCommodityAuctionDb/auctionHouse_97_1794126113_gzip.txt?verify=..."
}
```

#### `region_auctiondb`

```json
{
  "regionId": 2,
  "stringType": "AUCTIONDB_REGION_STAT",
  "lastModified": "1794099204",
  "url": "https://pricing-data.tradeskillmaster.com/pricing/regionStatDb/region_2_1794099204_gzip.txt?verify=..."
}
```

- `lastModified` arrives as a number **or** a numeric string, even within one
  burst. It is the time the addon gets as `downloadTime`.
- `auctionHouseType` is upper case and matches the user-realm entry.
- `url` points to `pricing-data.tradeskillmaster.com` (Cloudflare in front) and
  carries one query parameter, `verify` (a 54 character token). Earlier
  versions pointed at S3 style URLs on DigitalOcean Spaces with `X-Amz-*`
  parameters; 1.0.14 has none. The URL is used as received, unchanged and in
  particular with `verify` intact. It must be fetched **without** an
  Authorization header and without a `Range` header, with the undici header
  set. A 404 means the blob was superseded by newer data; the next event
  brings the new URL. The response is `200` with `Content-Type: text/plain`.
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

The object is a gzip file (`..._gzip.txt`). The 1.0.14 responses also carry a
`Content-Encoding: gzip` header, so a HTTP library may already have unpacked
it; the client therefore checks for the gzip magic (`1f 8b`) and decompresses
only when it is still there (`TSMApiClient.download`). The content is the Lua table that goes into
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

5 s doubling to 60 s after a dropped connection (the connect attempt times out
after 20 s); 5 s doubling to 300 s with
jitter after the server disconnects us (`41`/`44`, usually an expired or
rejected token). A token refresh while disconnected reconnects at once.

---

## AppData.lua

Written to `<WoW>/<folder>/Interface/AddOns/TradeSkillMaster_AppHelper/AppData.lua`,
but only for game versions where TradeSkillMaster or the AppHelper is installed.
The official 1.0.14 client writes this format; the addon reads it on login.

```lua
select(2, ...).LoadData("APP_INFO","Global",[[return {version="1.0.14",lastSync=1794128540,message={id=0,msg=""},news={...}}]]) --<APP_INFO,Global,1794128540>
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
  version the addon expects (`OFFICIAL_APP_VERSION` in `tsm/api/official.py`).

---

## Group sends

`tsm/core/services/group_sends.py`. On every socket connect and every `group_send` event the app sends
`POST /group-sends/claim` (node-fetch channel) with `{"gameTypes": [...]}`: the unique gameTypes of the installed
game folders (`_retail_` retail, `_classic_era_` and `_anniversary_` classic, `_classic_` classic-progression,
`_forever_` forever), in folder name order (the official client lists the WoW directory; the captured body was
`["forever","retail"]`). Skipped while the socket is down or no game version is installed.

- Claimed sends are saved to `~/.local/share/tsm-app/group_sends.json` (atomic) before anything is written to a
  game folder. A send stays pending until the addon marks its id `IMPORTED` or `DISCARDED` in
  `WTF/Account/*/SavedVariables/TradeSkillMaster_AppHelper.lua` (`groupImports`).
- Every installed game version gets `GROUP_IMPORTS`/`Global` in `AppData.lua` (replaced, never skipped for an older
  timestamp; removed when there is nothing to import; APP_INFO shares the key `Global` and is not touched).
  Timestamp is the newest `sentAt` (`floor(Date.parse(createdAt) / 1000)`).
- Import states are re-read at app start, after each claim and every 15 minutes with APP_INFO. The official client
  watches SavedVariables instead, so a handled send leaves our pending list later.
- Newly claimed sends raise the official notification text (title and body joined into one line) through the tray
  notification. There is no pending banner: a deliberate difference.

## Addon updates

The `addon` event lists the latest release per addon and channel. Each release
is one zip with a toc per client, installed unchanged into every game version
that already has the addon. Installs that are git checkouts, or whose toc reads
`@project-version@`, are left alone.

---

## Differences from the old API

| Old (`app-server /v2`, up to 1.1.16) | New |
|--------------------------------------|-----|
| Password grant, `legacy-desktop-app` client | PKCE login in an embedded window, `desktop-app` client |
| Session token from `/v2/auth`, lived about 10 minutes | Keycloak access token, refreshed with an offline refresh token |
| HMAC query parameters, plain HTTP | Bearer header, HTTPS |
| `endpointSubdomains` per session | Fixed hosts |
| Errors as HTTP 200 `{"success": false}` | HTTP status + NestJS error body |
| Poll `/v2/status` every hour | Socket pushes changes |
| Realms registered via `/v2/realms2/add` | `/user-realms`, shared with the official app |
| One addon zip per game version (`-Classic`, `-Progression`, ...) | One multi-toc zip per addon |
| Region strings `BCC-EU`, `Classic-EU` in the status payload | Built by the client from `gameVersion` + `regionPrefix` |
