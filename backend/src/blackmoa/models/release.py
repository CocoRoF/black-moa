"""다운로드 센터의 앱 설치본 (plan/64).

앱은 GitHub 릴리스로 나간다(태그 → CI 가 세 운영체제에서 굽는다). 저장소가 비공개라 사람은 GitHub 에서 받을 수
없으므로, 서버가 릴리스를 읽어 설치본을 제 저장소에 옮겨 두고 거기서 내어 준다. 여기 있는 것은 그 거울이다.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from blackmoa.db.base import Base, IdMixin


class AppRelease(Base, IdMixin):
    __tablename__ = "app_releases"
    tag: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), default="")
    #: 릴리스 노트(태그 메시지). 다운로드 센터가 그대로 보여 준다.
    notes: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prerelease: Mapped[bool] = mapped_column(Boolean, default=False)
    github_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: GitHub 에서 사라졌다(지웠거나 초안으로 되돌렸다). 목록에서 빼고 옮겨 둔 파일도 지운다.
    gone: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppReleaseAsset(Base, IdMixin):
    __tablename__ = "app_release_assets"
    release_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_releases.id", ondelete="CASCADE"), nullable=False, index=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: windows · macos · linux
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    #: x64 · arm64
    arch: Mapped[str] = mapped_column(String(16), nullable=False, default="x64")
    #: exe · dmg · AppImage · deb
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_path: Mapped[str | None] = mapped_column(Text)
    #: pending(아직 안 옮김) · ready · failed
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str] = mapped_column(Text, default="")
    tries: Mapped[int] = mapped_column(Integer, default=0)
    downloads: Mapped[int] = mapped_column(Integer, default=0)
    mirrored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
