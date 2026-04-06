"""
Custom Superset Security Manager.

Delegates username/password authentication to the FastAPI auth service.
On success it auto-provisions the user into Superset's own DB so that
roles and permissions work as normal.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests
from superset.security import SupersetSecurityManager

log = logging.getLogger(__name__)

AUTH_SERVICE_URL: str = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8000")
AUTH_SERVICE_TIMEOUT: int = int(os.getenv("AUTH_SERVICE_TIMEOUT", "10"))


class CustomAuthSecurityManager(SupersetSecurityManager):
    """
    Overrides DB-auth so that every login is validated against the external
    FastAPI auth service instead of Superset's local password store.

    The user is still synced into Superset's DB so that roles, dashboard
    ownership, etc. all work normally.
    """

    # ------------------------------------------------------------------
    # Core auth override
    # ------------------------------------------------------------------

    def auth_user_db(self, username, password):  # noqa: ANN001
        """Called by FAB for AUTH_DB logins."""
        if not username or not password:
            return None

        user_info = self._call_auth_service(username, password)
        if user_info is None:
            return None

        return self._sync_user(username, password, user_info)

    # ------------------------------------------------------------------
    # Helper: call the FastAPI auth service
    # ------------------------------------------------------------------

    def _call_auth_service(self, username: str, password: str) -> Optional[dict]:
        """
        POST /auth/login  →  { access_token, refresh_token, token_type }
        Then GET /auth/me with the token to retrieve full user info.
        Returns the user-info dict, or None on failure.
        """
        login_url = f"{AUTH_SERVICE_URL}/auth/login"
        me_url = f"{AUTH_SERVICE_URL}/auth/me"

        try:
            # FastAPI expects form-encoded body (OAuth2PasswordRequestForm)
            resp = requests.post(
                login_url,
                data={"username": username, "password": password},
                timeout=AUTH_SERVICE_TIMEOUT,
            )
        except requests.RequestException as exc:
            log.error("Auth service unreachable: %s", exc)
            flash("Authentication service unavailable. Please try again.", "danger")
            return None

        if resp.status_code != 200:
            log.warning(
                "Auth service rejected login for '%s': %s", username, resp.status_code
            )
            return None

        access_token: str = resp.json().get("access_token", "")
        if not access_token:
            log.error("Auth service returned no access_token for '%s'", username)
            return None

        # Fetch full profile
        try:
            me_resp = requests.get(
                me_url,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=AUTH_SERVICE_TIMEOUT,
            )
            me_resp.raise_for_status()
            return me_resp.json()
        except requests.RequestException as exc:
            log.error("Failed to fetch user profile from auth service: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Helper: sync user into Superset's local DB
    # ------------------------------------------------------------------

    def _sync_user(self, username: str, password: str, info: dict):
        """Find or create the Superset user record, update role from auth service."""
        email: str = info.get("email") or f"{username}@superset.local"
        first_name: str = info.get("first_name") or username
        last_name: str = info.get("last_name") or ""
        is_admin: bool = bool(info.get("is_admin", False))

        role_name = "Admin" if is_admin else "Alpha"
        role = self.find_role(role_name)
        if role is None:
            log.error("Superset role '%s' not found", role_name)
            return None

        user = self.find_user(username=username)

        if user is None:
            log.info("Auto-provisioning Superset user '%s' with role '%s'", username, role_name)
            user = self.add_user(
                username=username,
                first_name=first_name,
                last_name=last_name,
                email=email,
                role=role,
                # Password stored locally but never used for auth
                password=self.generate_password_hash(password),
            )
            if user is None:
                log.error("Failed to create Superset user '%s'", username)
                return None
        else:
            # Keep role in sync with auth service (compare by ID, not object identity)
            if {r.id for r in user.roles} != {role.id}:
                user.roles = [role]
                self.get_session.commit()

        return user
