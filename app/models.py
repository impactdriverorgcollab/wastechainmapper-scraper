"""
SQLAlchemy models mirroring the shared Postgres schema.
The scraper writes directly to Postgres (design decision: see API README).
PostGIS geography columns are handled via raw SQL — SQLAlchemy treats them as Text here
and we use text() expressions when inserting spatial data.
"""

import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, Float, Boolean, DateTime, Enum as PgEnum,
    ARRAY, JSON, func, text
)
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class GeocodeStatus(str, enum.Enum):
    PENDING = "PENDING"
    RESOLVED_GAZETTEER = "RESOLVED_GAZETTEER"
    RESOLVED_NOMINATIM = "RESOLVED_NOMINATIM"
    UNRESOLVED = "UNRESOLVED"


class VerificationStatus(str, enum.Enum):
    UNVERIFIED = "UNVERIFIED"
    CORROBORATED = "CORROBORATED"
    FIELD_VERIFIED = "FIELD_VERIFIED"
    REJECTED = "REJECTED"


class ReportSourceType(str, enum.Enum):
    NEWS_SCRAPE = "NEWS_SCRAPE"
    TWITTER_SCRAPE = "TWITTER_SCRAPE"
    WHATSAPP_CITIZEN = "WHATSAPP_CITIZEN"
    MANUAL_ENTRY = "MANUAL_ENTRY"


class WasteType(str, enum.Enum):
    MUNICIPAL = "MUNICIPAL"
    INDUSTRIAL = "INDUSTRIAL"
    MEDICAL = "MEDICAL"
    ELECTRONIC = "ELECTRONIC"
    CONSTRUCTION = "CONSTRUCTION"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class Report(Base):
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_text = Column(Text, nullable=False)
    source_url = Column(Text)
    source_type = Column(
        PgEnum("NEWS_SCRAPE", "TWITTER_SCRAPE", "WHATSAPP_CITIZEN", "MANUAL_ENTRY",
               name="ReportSourceType", create_type=False),
        nullable=False,
    )
    extracted_location_text = Column(Text)
    extracted_waste_type = Column(
        PgEnum("MUNICIPAL", "INDUSTRIAL", "MEDICAL", "ELECTRONIC",
               "CONSTRUCTION", "MIXED", "UNKNOWN", name="WasteType", create_type=False)
    )
    extracted_severity = Column(Text)
    extracted_urgency = Column(Text)
    geocode_status = Column(
        PgEnum("PENDING", "RESOLVED_GAZETTEER", "RESOLVED_NOMINATIM", "UNRESOLVED",
               name="GeocodeStatus", create_type=False),
        nullable=False,
        default="PENDING",
    )
    geocoded_latitude = Column(Float)
    geocoded_longitude = Column(Float)
    geocode_source = Column(Text)
    confidence_score = Column(Float)
    verification_status = Column(
        PgEnum("UNVERIFIED", "CORROBORATED", "FIELD_VERIFIED", "REJECTED",
               name="VerificationStatus", create_type=False),
        nullable=False,
        default="UNVERIFIED",
    )
    linked_site_id = Column(UUID(as_uuid=True))
    published_at = Column(DateTime(timezone=True))
    scraped_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type = Column(Text, nullable=False)
    status = Column(
        PgEnum("PENDING", "RUNNING", "DONE", "FAILED", name="JobStatus", create_type=False),
        nullable=False,
        default="PENDING",
    )
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    error_msg = Column(Text)
    metadata_ = Column("metadata", JSON)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
