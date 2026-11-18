"""Identity of the official TSM desktop client whose protocol this app speaks.

Single source for the official version and the User-Agent strings. The official
client identifies differently per channel: the Chromium renderer (Keycloak
login), node-fetch (REST), undici (Node fetch) and node-XMLHttpRequest (socket
long polling). Values come from a capture of the official 1.0.14 client.
"""

OFFICIAL_APP_VERSION = "1.0.14"
OFFICIAL_ELECTRON_VERSION = "44.4.3"
OFFICIAL_CHROMIUM_VERSION = "152.0.7977.130"

def chromium_user_agent_for(app_version: str) -> str:
    """The Chromium renderer User-Agent for a given app version."""
    return (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"TradeSkillMaster/{app_version} Chrome/{OFFICIAL_CHROMIUM_VERSION} "
        f"Electron/{OFFICIAL_ELECTRON_VERSION} Safari/537.36"
    )


UA_CHROMIUM = chromium_user_agent_for(OFFICIAL_APP_VERSION)
UA_NODE_FETCH = "node-fetch"
UA_UNDICI = "node"
UA_XHR = "node-XMLHttpRequest"
