import enum
from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, Float, ForeignKey, Enum, Text
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from db.security import encrypt_string, decrypt_string, hash_string

Base = declarative_base()

class WorkerType(str, enum.Enum):
    FESTANGESTELLT = "FESTANGESTELLT"
    MINIJOB = "MINIJOB"
    GEWERBE = "GEWERBE"
    SUBUNTERNEHMER = "SUBUNTERNEHMER"

class WorkerAccessRole(str, enum.Enum):
    COMPANY_OWNER = "company_owner"
    OBJEKTMANAGER = "objektmanager"
    ACCOUNTANT = "accountant"
    WORKER = "worker"
    SUBCONTRACTOR = "subcontractor"

class BillingType(str, enum.Enum):
    HOURLY = "HOURLY"
    FIXED = "FIXED"

class EventType(str, enum.Enum):
    CHECKIN = "CHECKIN"
    PAUSE_START = "PAUSE_START"
    PAUSE_END = "PAUSE_END"
    CHECKOUT = "CHECKOUT"

class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"

class PaymentType(str, enum.Enum):
    CONTRACT = "CONTRACT"
    OVERTIME = "OVERTIME"

class RequestStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    REJECTED = "rejected"

class CalendarEventType(str, enum.Enum):
    VACATION = "vacation"
    SICK_LEAVE = "sick_leave"
    PUBLIC_HOLIDAY = "public_holiday"
    NON_WORKING_DAY = "non_working_day"

class LanguageSupport(str, enum.Enum):
    DE = "de"
    UK = "uk"
    RO = "ro"
    PL = "pl"
    TR = "tr"
    RU = "ru"
    EN = "en"
    BG = "bg"
    SR = "sr"
    # Note: Moldovan uses 'ro' usually, but keeping distinct if needed, or mapping both to ro.
    OTHER = "other"

class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    owner_telegram_id_enc = Column(String, nullable=False)
    owner_telegram_id_hash = Column(String, nullable=False, index=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    website = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    sites = relationship("Site", back_populates="company")
    workers = relationship("Worker", back_populates="company")
    requests = relationship("Request", back_populates="company")
    calendar_events = relationship("CalendarEvent", back_populates="company")
    public_profile = relationship(
        "CompanyPublicProfile",
        back_populates="company",
        uselist=False,
    )


class CompanyPublicProfile(Base):
    __tablename__ = "company_public_profiles"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, unique=True)
    slug = Column(String(64), nullable=False, unique=True, index=True)
    company_name = Column(String, nullable=False)
    subtitle = Column(String, nullable=False)
    about_text = Column(Text, nullable=False)
    address = Column(String, nullable=False)
    email = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    company = relationship("Company", back_populates="public_profile")

class Site(Base):
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    address = Column(String)
    qr_token = Column(String, unique=True, index=True)
    is_active = Column(Boolean, default=True)
    
    # GPS validation properties
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    radius_m = Column(Float, nullable=True)

    company = relationship("Company", back_populates="sites")
    workers = relationship("Worker", back_populates="site")
    calendar_events = relationship("CalendarEvent", back_populates="site")

class Worker(Base):
    __tablename__ = "workers"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    
    # Security properties
    telegram_id_enc = Column(String, nullable=False)
    telegram_id_hash = Column(String, nullable=False, index=True)
    full_name_enc = Column(String, nullable=False)
    
    # Business logic
    worker_type = Column(Enum(WorkerType), nullable=False)
    billing_type = Column(Enum(BillingType), nullable=False)
    hourly_rate = Column(Float, nullable=True)
    contract_hours_week = Column(Integer, nullable=True)
    
    # App logic
    language = Column(Enum(LanguageSupport), default=LanguageSupport.DE)
    access_role = Column(
        String(32),
        nullable=False,
        default=WorkerAccessRole.WORKER.value,
        server_default=WorkerAccessRole.WORKER.value,
    )
    can_view_dashboard = Column(Boolean, default=False)
    time_tracking_enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    is_active = Column(Boolean, default=True)
    gdpr_consent_at = Column(DateTime(timezone=True), nullable=True)

    created_by = Column(Integer, ForeignKey("workers.id"), nullable=True)

    company = relationship("Company", back_populates="workers")
    site = relationship("Site", back_populates="workers")
    time_events = relationship("TimeEvent", back_populates="worker")
    payments = relationship("Payment", back_populates="worker", foreign_keys="Payment.worker_id")
    created_requests = relationship(
        "Request",
        back_populates="creator",
        foreign_keys="Request.created_by_worker_id",
    )
    targeted_requests = relationship(
        "Request",
        back_populates="target_worker",
        foreign_keys="Request.target_worker_id",
    )
    calendar_events = relationship(
        "CalendarEvent",
        back_populates="worker",
        foreign_keys="CalendarEvent.worker_id",
    )
    created_calendar_events = relationship(
        "CalendarEvent",
        back_populates="creator",
        foreign_keys="CalendarEvent.created_by_worker_id",
    )

class Request(Base):
    __tablename__ = "requests"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    created_by_worker_id = Column(Integer, ForeignKey("workers.id"), nullable=True)
    target_worker_id = Column(Integer, ForeignKey("workers.id"), nullable=True)
    related_date = Column(Date, nullable=True)
    text = Column(String, nullable=False)
    status = Column(
        String(20),
        nullable=False,
        default=RequestStatus.OPEN.value,
        server_default=RequestStatus.OPEN.value,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    company = relationship("Company", back_populates="requests")
    creator = relationship(
        "Worker",
        foreign_keys=[created_by_worker_id],
        back_populates="created_requests",
    )
    target_worker = relationship(
        "Worker",
        foreign_keys=[target_worker_id],
        back_populates="targeted_requests",
    )

class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    event_type = Column(String(32), nullable=False)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    comment = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    created_by_worker_id = Column(Integer, ForeignKey("workers.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    company = relationship("Company", back_populates="calendar_events")
    worker = relationship(
        "Worker",
        foreign_keys=[worker_id],
        back_populates="calendar_events",
    )
    site = relationship("Site", back_populates="calendar_events")
    creator = relationship(
        "Worker",
        foreign_keys=[created_by_worker_id],
        back_populates="created_calendar_events",
    )

class TimeEvent(Base):
    __tablename__ = "time_events"

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    event_type = Column(Enum(EventType), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    # Event location properties
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    gps_accuracy_m = Column(Float, nullable=True)
    is_suspicious = Column(Boolean, default=False)

    worker = relationship("Worker", back_populates="time_events")

class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    hours_paid = Column(Float, nullable=False)
    amount_paid = Column(Float, nullable=False)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING)
    payment_type = Column(String(20), nullable=False, default="OVERTIME", server_default="OVERTIME")
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    
    created_by = Column(Integer, ForeignKey("workers.id"), nullable=True)

    worker = relationship("Worker", back_populates="payments", foreign_keys=[worker_id])

class MonthlyAdjustment(Base):
    __tablename__ = "monthly_adjustments"

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    month = Column(Date, nullable=False)
    adjustment_minutes = Column(Integer, nullable=False)
    reason = Column(String(255), nullable=True)
    created_by = Column(Integer, ForeignKey("workers.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    worker = relationship("Worker", foreign_keys=[worker_id])

class DailySummary(Base):
    __tablename__ = "daily_summaries"

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    date = Column(Date, nullable=False)
    total_minutes = Column(Integer, default=0)
    break_minutes = Column(Integer, default=0)
    contract_minutes = Column(Integer, default=0)
    overtime_minutes = Column(Integer, default=0)

    worker = relationship("Worker", foreign_keys=[worker_id])
