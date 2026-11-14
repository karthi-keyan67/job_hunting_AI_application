import hashlib
import hmac
import base64
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, status
from pwdlib import PasswordHash
from pwdlib.exceptions import HasherNotAvailable
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.account import User
from app.repositories.auth import AuthRepository
from app.schemas.auth import TokenResponse

settings = get_settings()


class ScryptPasswordHasher:
    """Portable scrypt fallback used only where Argon2's native module is unavailable."""

    cost = 2**14
    block_size = 8
    parallelism = 1
    length = 64

    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=self.cost, r=self.block_size,
            p=self.parallelism, dklen=self.length, maxmem=128 * 1024 * 1024,
        )
        return "$scrypt${}${}${}${}${}".format(
            self.cost, self.block_size, self.parallelism,
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )

    def verify(self, password: str, encoded: str) -> bool:
        try:
            marker, algorithm, n, r, p, salt_value, digest_value = encoded.split("$")
            if marker or algorithm != "scrypt":
                return False
            salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
            expected = base64.urlsafe_b64decode(digest_value.encode("ascii"))
            actual = hashlib.scrypt(
                password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p),
                dklen=len(expected), maxmem=128 * 1024 * 1024,
            )
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False


try:
    password_hasher = PasswordHash.recommended()
except HasherNotAvailable:
    password_hasher = ScryptPasswordHasher()
_dummy_password_hash = password_hasher.hash("not-a-real-user-password")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_jwt(user_id: uuid.UUID, token_type: str, expires_at: datetime, family_id: uuid.UUID | None = None) -> str:
    claims: dict[str, str | int] = {
        "sub": str(user_id),
        "type": token_type,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    if family_id:
        claims["family"] = str(family_id)
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_jwt(token: str, expected_type: str) -> dict:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if claims.get("type") != expected_type:
            raise jwt.InvalidTokenError("wrong token type")
        return claims
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from exc


def _tokens_for_user(user: User, family_id: uuid.UUID | None = None) -> tuple[TokenResponse, str, datetime, uuid.UUID]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=settings.refresh_token_days)
    family = family_id or uuid.uuid4()
    access_expires = now + timedelta(minutes=settings.access_token_minutes)
    access = _create_jwt(user.id, "access", access_expires)
    refresh = _create_jwt(user.id, "refresh", expires, family)
    return TokenResponse(access_token=access, refresh_token=refresh, expires_in=settings.access_token_minutes * 60), _hash_token(refresh), expires, family


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = AuthRepository(session)

    async def register(self, email: str, password: str) -> tuple[User, TokenResponse]:
        normalized_email = email.strip().lower()
        if await self.repository.get_user_by_email(normalized_email):
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        user = await self.repository.create_user(normalized_email, password_hasher.hash(password))
        token_response, digest, expires, family = _tokens_for_user(user)
        await self.repository.add_refresh_token(user.id, digest, family, expires)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
        await self.session.refresh(user)
        return user, token_response

    async def login(self, email: str, password: str, client_ip: str | None = None) -> tuple[User, TokenResponse]:
        normalized_email = email.strip().lower()
        user = await self.repository.get_user_by_email(normalized_email)
        now = datetime.now(timezone.utc)
        window_seconds = settings.auth_login_window_minutes * 60
        window_started = datetime.fromtimestamp(int(now.timestamp()) // window_seconds * window_seconds, timezone.utc)
        fingerprint = hashlib.sha256(
            f"{settings.jwt_secret}\0{client_ip or 'unknown'}\0{normalized_email}".encode("utf-8")
        ).hexdigest()
        attempts = await self.repository.record_login_attempt(fingerprint, window_started)
        if attempts > settings.auth_login_max_attempts:
            await self.session.commit()
            retry_after = max(1, int((window_started + timedelta(seconds=window_seconds) - now).total_seconds()))
            raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.", headers={"Retry-After": str(retry_after)})
        valid = password_hasher.verify(password, user.password_hash if user else _dummy_password_hash)
        if user is None or not valid or not user.is_active:
            await self.session.commit()
            raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
        await self.repository.clear_login_attempt(fingerprint)
        token_response, digest, expires, family = _tokens_for_user(user)
        await self.repository.add_refresh_token(user.id, digest, family, expires)
        await self.session.commit()
        return user, token_response

    async def refresh(self, token: str) -> TokenResponse:
        claims = _decode_jwt(token, "refresh")
        try:
            user_id = uuid.UUID(claims["sub"])
            family = uuid.UUID(claims["family"])
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
        record = await self.repository.get_refresh_token(_hash_token(token))
        if record is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        if record.revoked_at is not None:
            await self.repository.revoke_family(record.family_id)
            await self.session.commit()
            raise HTTPException(status_code=401, detail="Refresh token has already been used")
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc) or record.user_id != user_id or record.family_id != family:
            await self.repository.revoke_token(record)
            await self.session.commit()
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        user = await self.repository.get_user(user_id)
        if user is None or not user.is_active:
            await self.repository.revoke_family(record.family_id)
            await self.session.commit()
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        response, digest, expires, _ = _tokens_for_user(user, record.family_id)
        await self.repository.revoke_token(record, digest)
        await self.repository.add_refresh_token(user.id, digest, record.family_id, expires)
        await self.session.commit()
        return response

    async def revoke_refresh_token(self, token: str, user_id: uuid.UUID) -> None:
        claims = _decode_jwt(token, "refresh")
        record = await self.repository.get_refresh_token(_hash_token(token))
        if record is None or record.user_id != user_id or claims.get("sub") != str(user_id):
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        await self.repository.revoke_family(record.family_id)
        await self.session.commit()


def decode_access_token(token: str) -> uuid.UUID:
    claims = _decode_jwt(token, "access")
    try:
        return uuid.UUID(claims["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from exc
