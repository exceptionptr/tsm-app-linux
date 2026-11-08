"""Auth models.

The login is an OpenID Connect browser login against Keycloak
(id.tradeskillmaster.com, see tsm/api/oidc.py). Every TSM service takes the
resulting access token directly; there is no separate TSM session any more.
UserSession is the account view the UI needs. The tokens themselves live in
AuthService, and the refresh token in the keyring.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class UserSession(BaseModel):
    username: str
    user_id: str = ""  # Keycloak subject, used by the user-realms API
    premium_tier: str | None = None  # "platinum" | "gold" | None
    release_channels: list[str] = Field(default_factory=lambda: ["release"])
    # True when "Remember me" was asked for but the keyring refused the login.
    remember_failed: bool = False

    @property
    def realm_limit(self) -> int | None:
        """How many realms the account may follow; None means unlimited."""
        if self.premium_tier == "platinum":
            return None
        if self.premium_tier == "gold":
            return 25
        return 10
