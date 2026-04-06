"""
Superset configuration — custom auth via external FastAPI service.
"""

import os
from custom_security import CustomAuthSecurityManager
from flask_appbuilder.security.manager import AUTH_DB

# ------------------------------------------------------------------
# Core secrets
# ------------------------------------------------------------------

SECRET_KEY = os.getenv("SUPERSET_SECRET_KEY", "change-me-superset-secret")

# ------------------------------------------------------------------
# Database (Postgres via docker-compose)
# ------------------------------------------------------------------

SQLALCHEMY_DATABASE_URI = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://superset:superset@db:5432/superset",
)

# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------

# Delegate authentication to our custom manager
CUSTOM_SECURITY_MANAGER = CustomAuthSecurityManager

# Use the standard DB-auth flow (username + password form) so FAB
# renders the normal login page and calls auth_user_db for us.
AUTH_TYPE = AUTH_DB

# Disable FAB's built-in self-registration form — it requires ReCaptcha
# keys and is not needed here. User accounts are created via the FastAPI
# auth service (/auth/register) and auto-provisioned in Superset on first
# successful login through our custom SecurityManager.
AUTH_USER_REGISTRATION = False

# ------------------------------------------------------------------
# Feature flags
# ------------------------------------------------------------------

FEATURE_FLAGS = {
    "ENABLE_TEMPLATE_PROCESSING": True,
}

# ------------------------------------------------------------------
# Cache / sessions (simple in-memory defaults; swap for Redis in prod)
# ------------------------------------------------------------------

CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache"}

# ------------------------------------------------------------------
# Misc
# ------------------------------------------------------------------

SUPERSET_WEBSERVER_PORT = 8088
ROW_LIMIT = 5000
SUPERSET_WEBSERVER_TIMEOUT = 300

# Silence the "allow_renderer_requests" deprecation noise
SILENCE_FAB = False
