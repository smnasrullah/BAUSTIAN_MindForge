from sqlalchemy import Double, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigIntPK


class RateLimitHit(Base):
    """One allowed request in a shared (all-worker) sliding-window limit; see core/shared_limit."""

    __tablename__ = "rate_limit_hits"
    __table_args__ = (Index("ix_rate_limit_hits_bucket_at", "bucket", "hit_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    bucket: Mapped[str] = mapped_column(Text)
    hit_at: Mapped[float] = mapped_column(Double)  # unix epoch seconds
