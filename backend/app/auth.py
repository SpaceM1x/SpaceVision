from datetime import datetime, timedelta, timezone

import base64
import hashlib
import hmac
import secrets

import jwt

SECRET_KEY = "change-this-in-env"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 120_000
    )
    return (
        f"pbkdf2_sha256$120000$"
        f"{base64.urlsafe_b64encode(salt).decode('ascii')}$"
        f"{base64.urlsafe_b64encode(derived_key).decode('ascii')}"
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        algorithm, rounds, salt_b64, hash_b64 = hashed_password.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected_hash = base64.urlsafe_b64decode(hash_b64.encode("ascii"))
        calculated_hash = hashlib.pbkdf2_hmac(
            "sha256", plain_password.encode("utf-8"), salt, int(rounds)
        )
        return hmac.compare_digest(calculated_hash, expected_hash)
    except (ValueError, TypeError):
        return False


def create_access_token(username: str, role: str) -> str:
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
