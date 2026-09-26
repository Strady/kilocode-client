"""Authentication helpers for the Kilo server.

The server uses HTTP Basic Auth. Credentials are most often provided through the
``KILO_SERVER_USERNAME`` and ``KILO_SERVER_PASSWORD`` environment variables. When no
password is configured the server accepts unauthenticated local requests, so the
client silently sends no ``Authorization`` header in that case.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Credentials:
    username: Optional[str]
    password: Optional[str]

    @property
    def enabled(self) -> bool:
        """Basic auth is only sent when a password is provided."""
        return bool(self.password)

    @property
    def header_value(self) -> Optional[str]:
        """Value for the ``Authorization`` header, or ``None`` when auth is off."""
        if not self.enabled:
            return None
        user = self.username or "kilo"
        token = base64.b64encode(f"{user}:{self.password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"


def credentials_from_env(
    username_env: str = "KILO_SERVER_USERNAME",
    password_env: str = "KILO_SERVER_PASSWORD",
) -> Credentials:
    """Build credentials from the environment.

    Matches the server's defaults: the username defaults to ``"kilo"`` when
    ``KILO_SERVER_USERNAME`` is not set. If ``KILO_SERVER_PASSWORD`` is empty/unset,
    auth is disabled entirely (the server runs without a password locally).
    """
    username = os.environ.get(username_env)
    password = os.environ.get(password_env)
    # A deliberately empty password means "no auth required" -- normalize None to
    # distinguish "not provided" from "provided but blank".
    return Credentials(username=username or "kilo", password=password)


def make_headers(
    username: Optional[str] = None,
    password: Optional[str] = None,
    base: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Build request headers, conditionally including Basic Auth.

    If only ``username`` is given without a ``password``, no auth header is emitted
    (unless an ``Authorization`` header already exists in ``base``).
    """
    headers: dict[str, str] = dict(base or {})
    if "Authorization" in headers:
        return headers
    creds = Credentials(username=username, password=password) if (username or password) else None
    if creds is None:
        return headers
    value = creds.header_value
    if value:
        headers["Authorization"] = value
    return headers