import base64
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import HTTPException
from passlib.context import CryptContext

logger = logging.getLogger(__name__)

# Secret key for JWT token – MUST be set via environment variable in production
_default_secret = "CHANGE_ME_IN_PRODUCTION"
SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", _default_secret)
if SECRET_KEY == _default_secret:
    logger.warning(
        "JWT_SECRET_KEY is not set – using insecure default. "
        "Set the JWT_SECRET_KEY environment variable before deploying."
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "30"))

# Password hashing — bcrypt with SHA-256 pre-hash to handle passwords >72 bytes.
# bcrypt silently truncates at 72 bytes; pre-hashing avoids that limit while
# keeping the full bcrypt cost factor for brute-force resistance.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _prepare_password(password: str) -> str:
    """SHA-256 + base64 encode so bcrypt never sees >72 bytes."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Encode a JWT access token using PyJWT (HS256)."""
    to_encode = data.copy()
    expire = (
        datetime.now(timezone.utc) + expires_delta
        if expires_delta
        else datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str, credentials_exception):
    """Decode and validate a JWT token. Raises credentials_exception on failure."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except jwt.InvalidTokenError:
        raise credentials_exception


def hash_password(password: str) -> str:
    return pwd_context.hash(_prepare_password(password))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(_prepare_password(plain_password), hashed_password)