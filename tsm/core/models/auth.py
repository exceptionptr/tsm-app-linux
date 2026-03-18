"""Auth models.

The TSM API uses a two-step auth:
1. OIDC JWT from Keycloak (id.tradeskillmaster.com)
2. TSM session token returned by /v2/auth — stored as user_info["session"]

We only keep the high-level UserSession here; the raw OIDC token is stored in
keyring and the TSM session string lives inside TSMApiClient._user_info.
"""

from __future__ import annotations

from pydantic import BaseModel


class UserSession(BaseModel):
    username: str
    user_id: int = 0
