# backend/models/member.py
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class MemberModel(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    skills: Mapped[str] = mapped_column(String(500), default="")
    load_pct: Mapped[int] = mapped_column(Integer, default=0)
