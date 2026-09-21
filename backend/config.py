# backend/config.py
"""アプリ全体の設定値を一元管理する（DB接続文字列など）"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "sqlite+aiosqlite:///./tasumiru.db"

    # 認証セッションCookieの設定（本番ではHTTPS配信のためCOOKIE_SECURE=trueにする）
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
