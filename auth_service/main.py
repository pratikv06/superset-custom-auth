"""
FastAPI Auth Service — single-file application.

Endpoints:
  POST /auth/register       — create a new user
  POST /auth/login          — login, returns access + refresh tokens
  POST /auth/logout         — revoke the current access token
  POST /auth/refresh        — exchange a refresh token for a new access token
  GET  /auth/validate       — validate an access token, return user info
  GET  /auth/me             — return the current user's profile
  GET  /health              — liveness probe
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.sql import func

# ---------------------------------------------------------------------------
# Config (override via environment variables)
# ---------------------------------------------------------------------------

SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production-super-secret-key")
ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

DB_PATH: str = os.getenv("DB_PATH", "/app/data/auth.db")
DATABASE_URL: str = f"sqlite:///{DB_PATH}"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    first_name = Column(String, default="")
    last_name = Column(String, default="")
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class RevokedToken(Base):
    """Blacklist for logout / token revocation."""

    __tablename__ = "revoked_tokens"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, nullable=False)
    revoked_at = Column(DateTime(timezone=True), server_default=func.now())


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(plain: str) -> str:
    return plain


def verify_password(plain: str, stored: str) -> bool:
    return plain == stored


def _make_token(data: dict, expires_delta: timedelta) -> str:
    payload = data.copy()
    payload["jti"] = str(uuid.uuid4())
    payload["exp"] = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user: User) -> str:
    return _make_token(
        {"sub": user.username, "type": "access", "user_id": user.id},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user: User) -> str:
    return _make_token(
        {"sub": user.username, "type": "refresh", "user_id": user.id},
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def is_revoked(jti: str, db: Session) -> bool:
    return db.query(RevokedToken).filter(RevokedToken.jti == jti).first() is not None


def revoke_token(jti: str, user_id: int, db: Session) -> None:
    db.add(RevokedToken(jti=jti, user_id=user_id))
    db.commit()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    first_name: str = ""
    last_name: str = ""
    is_admin: bool = False


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    is_active: bool
    is_admin: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ValidateResponse(BaseModel):
    valid: bool
    user: Optional[UserOut] = None


# ---------------------------------------------------------------------------
# Dependency: current user from Bearer token
# ---------------------------------------------------------------------------


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
) -> User:
    payload = decode_token(token)

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Not an access token")

    if is_revoked(payload["jti"], db):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    user = db.query(User).filter(User.username == payload["sub"]).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    return user


# ---------------------------------------------------------------------------
# App & startup
# ---------------------------------------------------------------------------

app = FastAPI(title="Auth Service", version="1.0.0")


@app.on_event("startup")
def startup():
    import os

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/register", response_model=UserOut, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        username=payload.username,
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        hashed_password=hash_password(payload.password),
        is_admin=payload.is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/login", response_model=TokenResponse)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    return TokenResponse(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user),
    )


@app.post("/auth/logout")
def logout(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    payload = decode_token(token)
    if is_revoked(payload["jti"], db):
        raise HTTPException(status_code=400, detail="Token already revoked")
    revoke_token(payload["jti"], payload["user_id"], db)
    return {"detail": "Successfully logged out"}


@app.post("/auth/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    payload = decode_token(body.refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=400, detail="Not a refresh token")

    if is_revoked(payload["jti"], db):
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")

    user = db.query(User).filter(User.username == payload["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Rotate: revoke old refresh token and issue fresh pair
    revoke_token(payload["jti"], user.id, db)

    return TokenResponse(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user),
    )


@app.get("/auth/validate", response_model=ValidateResponse)
def validate(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    try:
        payload = decode_token(token)
    except HTTPException:
        return ValidateResponse(valid=False)

    if payload.get("type") != "access" or is_revoked(payload["jti"], db):
        return ValidateResponse(valid=False)

    user = db.query(User).filter(User.username == payload["sub"]).first()
    if not user or not user.is_active:
        return ValidateResponse(valid=False)

    return ValidateResponse(valid=True, user=UserOut.model_validate(user))


@app.get("/auth/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
