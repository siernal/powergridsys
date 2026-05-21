"""
core/security.py — JWT и хеширование паролей.

Используется bcrypt напрямую (без passlib), потому что passlib 1.7.4
несовместим с bcrypt >= 4.1: passlib обращается к bcrypt.__about__,
которого больше нет, и падает на внутреннем тесте detect_wrap_bug.
"""
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from core.config import get_settings
from core.database import get_db

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def get_password_hash(password: str) -> str:
    """Хешируем пароль через bcrypt напрямую.
    bcrypt принимает максимум 72 байта; для безопасности обрезаем заранее."""
    pw_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Проверка пароля. Возвращает False при любых ошибках формата."""
    try:
        pw_bytes = plain.encode("utf-8")[:72]
        return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """Возвращает текущего пользователя или None.
    В демо-режиме большинство эндпоинтов открыты для неавторизованных запросов."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None

    from models import User
    return db.query(User).filter(User.username == username).first()
