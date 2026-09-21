# backend/auth/token_service.py
"""
トークンの生成・ハッシュ化のみを担当する（DBやFastAPIへの依存を持たない）。

- 生トークンは暗号学的に安全な乱数から生成する（secrets.token_urlsafe）。
- DBには生トークンではなく SHA-256 ハッシュのみを保存する。
  ランダムトークンは十分なエントロピー（ここでは256bit）を持つため、
  パスワードのような低エントロピーな秘密情報向けの低速ハッシュ（bcrypt等）は不要で、
  高速な暗号学的ハッシュで十分（GitHub Personal Access Token等と同様の方式）。
"""

import hashlib
import secrets
from datetime import datetime, timezone

TOKEN_BYTES = 32  # 256bit


def generate_token() -> str:
    """URLセーフな暗号学的に安全なランダムトークンを生成する"""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw_token: str) -> str:
    """トークンのSHA-256ハッシュ（16進文字列）を返す"""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def ensure_utc(dt: datetime) -> datetime:
    """SQLiteはtimezone情報を保持しないため、naiveな値が来た場合はUTCとして扱う"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
