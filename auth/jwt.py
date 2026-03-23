import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from jose import JWTError, jwt
from passlib.context import CryptContext

import logging

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

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Create a JWT Token

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Verify the JWT Token

def verify_token(token: str, credentials_exception):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception

# Function to hash password

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

# Function to verify password

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)