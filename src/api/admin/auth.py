"""HTTP Basic authentication for the admin surface.

There is no end-user authentication in v1 and this does not introduce any: it
guards the admin routes only, and the rescue flow stays open to anonymous
visitors.

Two properties this file exists to hold:

* **A refusal discloses nothing.** Not whether the username exists, not whether
  admin is configured at all. The comparison is constant-time and every failure
  returns one identical response.
* **Unconfigured means closed.** If `ADMIN_USERNAME` or `ADMIN_PASSWORD` is
  empty the admin surface refuses everyone, rather than defaulting to open. A
  deployment that forgot to set them gets a locked door, not an unlocked one.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from src.core.config import Settings, get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)

#: `auto_error=False` so a missing header reaches our handler rather than
#: FastAPI's, which would answer without the `WWW-Authenticate` challenge and
#: with a body of its own choosing.
_basic = HTTPBasic(auto_error=False, description="Admin credentials from environment")

#: One response for every rejection. Wrong password, unknown user, missing
#: header, and admin-not-configured are indistinguishable from outside — the
#: differences are useful only to someone probing.
_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="احراز هویت مدیر لازم است.",
    headers={"WWW-Authenticate": 'Basic realm="liara-rescue-admin"'},
)


def _matches(candidate: str, expected: str) -> bool:
    """Constant-time comparison, so timing does not leak the correct prefix."""
    return secrets.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def require_admin(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    """Return the authenticated admin username, or refuse without disclosing why."""
    expected_user = settings.admin_username
    expected_password = settings.admin_password

    if not expected_user or not expected_password:
        # Closed by default. An admin surface that opens itself because a
        # variable is missing is worse than one that is simply unavailable.
        logger.error("admin surface is unconfigured; refusing all admin requests")
        raise _UNAUTHORIZED

    if credentials is None:
        raise _UNAUTHORIZED

    # Both comparisons always run: short-circuiting on the username would make
    # a wrong username measurably faster than a wrong password.
    user_ok = _matches(credentials.username, expected_user)
    password_ok = _matches(credentials.password, expected_password)
    if not (user_ok and password_ok):
        # The attempted username is deliberately not logged. It is attacker-
        # controlled, and a real operator typing their password into the
        # username field would otherwise write it to the log.
        logger.warning("admin authentication failed")
        raise _UNAUTHORIZED

    return credentials.username


AdminUser = Annotated[str, Depends(require_admin)]
