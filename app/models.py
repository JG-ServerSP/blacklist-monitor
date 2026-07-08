import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Role(str, enum.Enum):
    admin = "admin"
    operator = "operator"
    readonly = "readonly"


class PingMode(str, enum.Enum):
    skip_unreachable = "skip_unreachable"
    check_all = "check_all"
    tcp_fallback = "tcp_fallback"


class PingStatus(str, enum.Enum):
    unknown = "unknown"
    up = "up"
    unreachable = "unreachable"


class IPStatus(str, enum.Enum):
    clean = "clean"
    listed = "listed"
    unchecked = "unchecked"
    error = "error"


class BLType(str, enum.Enum):
    ipv4 = "ipv4"
    ipv6 = "ipv6"
    domain = "domain"


class Severity(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class ListingStatus(str, enum.Enum):
    detected = "detected"
    notified = "notified"
    delist_requested = "delist_requested"
    observing = "observing"
    removed = "removed"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False, default="")
    password_hash = Column(String, nullable=False)
    role = Column(Enum(Role), default=Role.operator, nullable=False)
    totp_secret = Column(String, nullable=True)
    totp_enabled = Column(Boolean, default=False)
    api_token_hash = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Canais pessoais de notificação (perfil do usuário, Configurações -> Minha
    # Conta). notify_email cai para o e-mail de login quando vazio.
    notify_email = Column(String, nullable=True)
    pushover_user_key = Column(String, nullable=True)
    # Idioma pessoal (sobrepõe Settings.language só para este usuário). None = usa o idioma do sistema.
    language = Column(String, nullable=True)


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    external_id = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    services = relationship("Service", back_populates="client")


class Service(Base):
    __tablename__ = "services"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=True)
    external_ref = Column(String, nullable=True)

    client = relationship("Client", back_populates="services")


class IPGroup(Base):
    __tablename__ = "ip_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    datacenter = Column(String, nullable=True)
    ping_mode = Column(Enum(PingMode), default=PingMode.skip_unreachable)
    check_interval_minutes = Column(Integer, nullable=True)
    settings = Column(JSON, default=dict)


class IPBlock(Base):
    __tablename__ = "ip_blocks"
    id = Column(Integer, primary_key=True)
    cidr = Column(String, nullable=False)
    group_id = Column(Integer, ForeignKey("ip_groups.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=True)
    asn = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MonitoredIP(Base):
    __tablename__ = "monitored_ips"
    id = Column(Integer, primary_key=True)
    ip = Column(String, unique=True, index=True, nullable=False)
    block_id = Column(Integer, ForeignKey("ip_blocks.id"), nullable=True)
    group_id = Column(Integer, ForeignKey("ip_groups.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=True)
    asn = Column(String, nullable=True)
    datacenter = Column(String, nullable=True)
    tags = Column(String, nullable=True)
    enabled = Column(Boolean, default=True)
    ping_status = Column(Enum(PingStatus), default=PingStatus.unknown)
    last_ping_at = Column(DateTime, nullable=True)
    current_status = Column(Enum(IPStatus), default=IPStatus.unchecked)
    risk_score = Column(Integer, default=0)
    last_checked_at = Column(DateTime, nullable=True)
    # None = herda do grupo (IPGroup.check_interval_minutes) e, na ausência
    # deste, do intervalo global (Settings.default_check_interval_minutes).
    check_interval_minutes = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client")
    service = relationship("Service")
    group = relationship("IPGroup")
    listings = relationship(
        "Listing",
        back_populates="ip",
        order_by="desc(Listing.detected_at)",
        cascade="all, delete-orphan",
    )


class Domain(Base):
    __tablename__ = "domains"
    id = Column(Integer, primary_key=True)
    domain = Column(String, unique=True, index=True, nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=True)
    enabled = Column(Boolean, default=True)
    current_status = Column(Enum(IPStatus), default=IPStatus.unchecked)
    last_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client")
    service = relationship("Service")
    listings = relationship(
        "Listing",
        back_populates="domain",
        cascade="all, delete-orphan",
    )


class Blacklist(Base):
    __tablename__ = "blacklists"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    zone = Column(String, nullable=False)  # e.g. zen.dq.spamhaus.net, may contain {key}
    type = Column(Enum(BLType), default=BLType.ipv4)
    default_severity = Column(Enum(Severity), default=Severity.medium)
    return_code_map = Column(JSON, default=dict)  # {"127.0.0.2": {"sublist": "SBL", "severity": "critical"}}
    delist_url = Column(String, nullable=True)
    lookup_url = Column(String, nullable=True)
    rate_limit_qps = Column(Float, default=5.0)
    enabled = Column(Boolean, default=True)
    requires_key = Column(Boolean, default=False)
    api_key_encrypted = Column(String, nullable=True)


class Listing(Base):
    __tablename__ = "listings"
    id = Column(Integer, primary_key=True)
    ip_id = Column(Integer, ForeignKey("monitored_ips.id"), nullable=True)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=True)
    blacklist_id = Column(Integer, ForeignKey("blacklists.id"), nullable=False)
    sublist = Column(String, nullable=True)
    severity = Column(Enum(Severity), default=Severity.medium)
    detected_at = Column(DateTime, default=datetime.utcnow)
    removed_at = Column(DateTime, nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    txt_reason = Column(Text, nullable=True)
    status = Column(Enum(ListingStatus), default=ListingStatus.detected)
    delist_requested_by = Column(String, nullable=True)
    delist_requested_at = Column(DateTime, nullable=True)
    ticket_ref = Column(String, nullable=True)

    ip = relationship("MonitoredIP", back_populates="listings")
    domain = relationship("Domain", back_populates="listings")
    blacklist = relationship("Blacklist")
    notifications = relationship(
        "Notification",
        back_populates="listing",
        cascade="all, delete-orphan",
    )


class CheckRun(Base):
    __tablename__ = "check_runs"
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    ips_checked = Column(Integer, default=0)
    ips_skipped_ping = Column(Integer, default=0)
    errors = Column(Integer, default=0)


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    conditions = Column(JSON, default=dict)  # {"min_severity": "high", "blacklist_id": None, "group_id": None, "client_id": None, "recurrent_only": False, "on_resolution": False, "on_error": False}
    channels = Column(JSON, default=list)  # [{"type": "email", "to": "noc@x.com"}, {"type": "pushover", "user_key": "..."}]
    escalation = Column(JSON, default=dict)  # {"minutes": 30, "channels": [...]}
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=True)
    rule_id = Column(Integer, ForeignKey("alert_rules.id"), nullable=True)
    channel = Column(String, nullable=False)
    recipient = Column(String, nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="sent")
    error = Column(Text, nullable=True)

    listing = relationship("Listing", back_populates="notifications")


class ActivityLog(Base):
    __tablename__ = "activity_log"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)
    entity = Column(String, nullable=True)
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class SettingKV(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value_encrypted = Column(Text, nullable=True)
