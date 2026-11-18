"""Pure helpers of the embedded login window."""


from tsm.api import chromium


def test_callback_is_recognised_without_port_only():
    assert chromium.is_callback_url("http://localhost/auth/callback?code=a&state=b")
    assert chromium.is_callback_url("http://localhost/auth/callback")
    assert not chromium.is_callback_url("http://localhost:1234/auth/callback?code=a")
    assert not chromium.is_callback_url("http://127.0.0.1/auth/callback")
    assert not chromium.is_callback_url("https://localhost/auth/callback")
    assert not chromium.is_callback_url("http://localhost/other")


def test_parse_callback_returns_the_query_or_none():
    assert chromium.parse_callback("http://localhost/auth/callback?state=s&code=c%2Bd") == {
        "state": "s",
        "code": "c+d",
    }
    assert chromium.parse_callback(
        "http://localhost/auth/callback?error=access_denied&error_description=No%20way"
    ) == {"error": "access_denied", "error_description": "No way"}
    assert chromium.parse_callback("https://example.com/auth/callback?code=x") is None


def test_navigation_guard_stays_on_the_auth_origin():
    base = "https://id.tradeskillmaster.com/realms/app/protocol/openid-connect/auth?x=1"
    assert chromium.is_allowed_navigation(base)
    assert chromium.is_allowed_navigation("http://localhost/auth/callback?code=a")
    assert not chromium.is_allowed_navigation("http://id.tradeskillmaster.com/x")
    assert not chromium.is_allowed_navigation("https://id.tradeskillmaster.com.example.com/")
    assert not chromium.is_allowed_navigation("https://example.com/")
    assert not chromium.is_allowed_navigation("file:///etc/passwd")
    assert not chromium.is_allowed_navigation("https://id.tradeskillmaster.com:8443/")


def test_client_hint_values_match_the_capture():
    assert chromium.SEC_CH_UA == '"Not?A_Brand";v="24", "Chromium";v="152"'
    assert chromium.CLIENT_PLATFORM == "Linux"
    assert chromium.ACCEPT_LANGUAGE == "en-US"
    assert chromium.FULL_VERSION_LIST["Chromium"] == "152.0.7977.130"
