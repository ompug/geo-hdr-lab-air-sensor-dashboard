from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, delete
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app.config import Settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Sensor(Base):
    __tablename__ = "sensors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    hostname: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    mac: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    firmware_version: Mapped[str | None] = mapped_column(String(128))
    esphome_version: Mapped[str | None] = mapped_column(String(128))
    device_title: Mapped[str | None] = mapped_column(String(255))
    entities_json: Mapped[str | None] = mapped_column(Text)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    online: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    readings: Mapped[list["Reading"]] = relationship(
        back_populates="sensor", cascade="all, delete-orphan"
    )


class Reading(Base):
    __tablename__ = "readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sensor_id: Mapped[str] = mapped_column(
        ForeignKey("sensors.id", ondelete="CASCADE"), index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    co2: Mapped[float | None] = mapped_column(Float)
    pm1_0: Mapped[float | None] = mapped_column(Float)
    pm2_5: Mapped[float | None] = mapped_column(Float)
    pm4_0: Mapped[float | None] = mapped_column(Float)
    pm10: Mapped[float | None] = mapped_column(Float)
    voc: Mapped[float | None] = mapped_column(Float)
    nox: Mapped[float | None] = mapped_column(Float)
    temperature: Mapped[float | None] = mapped_column(Float)
    humidity: Mapped[float | None] = mapped_column(Float)
    pressure: Mapped[float | None] = mapped_column(Float)
    rssi: Mapped[float | None] = mapped_column(Float)
    nowcast_aqi: Mapped[float | None] = mapped_column(Float)
    esp_temperature: Mapped[float | None] = mapped_column(Float)
    carbon_monoxide: Mapped[float | None] = mapped_column(Float)
    methane: Mapped[float | None] = mapped_column(Float)
    ethanol: Mapped[float | None] = mapped_column(Float)
    hydrogen: Mapped[float | None] = mapped_column(Float)
    ammonia: Mapped[float | None] = mapped_column(Float)
    nitrogen_dioxide: Mapped[float | None] = mapped_column(Float)
    pm_0_3_to_1: Mapped[float | None] = mapped_column(Float)
    pm_1_to_2_5: Mapped[float | None] = mapped_column(Float)
    pm_2_5_to_4: Mapped[float | None] = mapped_column(Float)
    pm_4_to_10: Mapped[float | None] = mapped_column(Float)
    sensor: Mapped[Sensor] = relationship(back_populates="readings")


READING_FIELDS = tuple(
    column.name
    for column in Reading.__table__.columns
    if column.name not in {"id", "sensor_id", "timestamp"}
)


class Database:
    def __init__(self, settings: Settings):
        Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
        self.session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, class_=Session
        )

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)

    def session(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session

    def cleanup(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = utcnow() - timedelta(days=retention_days)
        with self.session_factory.begin() as session:
            result = session.execute(delete(Reading).where(Reading.timestamp < cutoff))
            return result.rowcount or 0
