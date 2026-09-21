# backend/db/base.py
"""全SQLAlchemyモデルが継承する宣言的ベースクラス"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
