from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models import BLType, IPStatus, ListingStatus, PingMode, PingStatus, Role, Severity


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth ----------
class LoginRequest(BaseModel):
    email: str
    password: str
    totp_code: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserCreate(BaseModel):
    email: str
    name: str = ""
    password: str
    role: Role = Role.operator


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[Role] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class UserOut(ORMModel):
    id: int
    email: str
    name: str
    role: Role
    totp_enabled: bool
    is_active: bool
    created_at: datetime
    notify_email: Optional[str] = None
    pushover_user_key: Optional[str] = None
    language: Optional[str] = None


class NotifyProfileUpdate(BaseModel):
    notify_email: Optional[str] = None
    pushover_user_key: Optional[str] = None


class LanguageUpdate(BaseModel):
    language: str


# ---------- Client / Service / Group ----------
class ClientCreate(BaseModel):
    name: str
    external_id: Optional[str] = None
    contact_email: Optional[str] = None


class ClientOut(ORMModel):
    id: int
    name: str
    external_id: Optional[str] = None
    contact_email: Optional[str] = None
    created_at: datetime


class ServiceCreate(BaseModel):
    client_id: Optional[int] = None
    name: str
    type: Optional[str] = None
    external_ref: Optional[str] = None


class ServiceOut(ORMModel):
    id: int
    client_id: Optional[int]
    name: str
    type: Optional[str]
    external_ref: Optional[str]


class IPGroupCreate(BaseModel):
    name: str
    datacenter: Optional[str] = None
    ping_mode: PingMode = PingMode.skip_unreachable
    check_interval_minutes: Optional[int] = None
    settings: dict = {}


class IPGroupOut(ORMModel):
    id: int
    name: str
    datacenter: Optional[str]
    ping_mode: PingMode
    check_interval_minutes: Optional[int]
    settings: dict


# ---------- IPs ----------
class IPImportRequest(BaseModel):
    entry: str  # CIDR, range "a-b", or single IP
    client_id: Optional[int] = None
    service_id: Optional[int] = None
    group_id: Optional[int] = None
    datacenter: Optional[str] = None
    tags: Optional[str] = None
    asn: Optional[str] = None
    check_interval_minutes: Optional[int] = None


class IPBlockOut(ORMModel):
    id: int
    cidr: str
    group_id: Optional[int]
    client_id: Optional[int]
    service_id: Optional[int]
    asn: Optional[str]
    note: Optional[str]
    created_at: datetime
    ip_count: int = 0


class MonitoredIPOut(ORMModel):
    id: int
    ip: str
    block_id: Optional[int]
    group_id: Optional[int]
    client_id: Optional[int]
    service_id: Optional[int]
    asn: Optional[str]
    datacenter: Optional[str]
    tags: Optional[str]
    enabled: bool
    ping_status: PingStatus
    last_ping_at: Optional[datetime]
    current_status: IPStatus
    risk_score: int
    last_checked_at: Optional[datetime]
    check_interval_minutes: Optional[int]
    created_at: datetime


class BulkIdsRequest(BaseModel):
    ids: list[int]


class BulkIPUpdateRequest(BaseModel):
    ids: list[int]
    enabled: Optional[bool] = None
    client_id: Optional[int] = None
    service_id: Optional[int] = None
    group_id: Optional[int] = None
    datacenter: Optional[str] = None
    tags: Optional[str] = None
    check_interval_minutes: Optional[int] = None


class MonitoredIPUpdate(BaseModel):
    enabled: Optional[bool] = None
    client_id: Optional[int] = None
    service_id: Optional[int] = None
    group_id: Optional[int] = None
    datacenter: Optional[str] = None
    tags: Optional[str] = None
    check_interval_minutes: Optional[int] = None


class DomainCreate(BaseModel):
    domain: str
    client_id: Optional[int] = None
    service_id: Optional[int] = None


class DomainOut(ORMModel):
    id: int
    domain: str
    client_id: Optional[int]
    service_id: Optional[int]
    enabled: bool
    current_status: IPStatus
    last_checked_at: Optional[datetime]
    created_at: datetime


# ---------- Blacklists ----------
class BlacklistCreate(BaseModel):
    name: str
    zone: str
    type: BLType = BLType.ipv4
    default_severity: Severity = Severity.medium
    return_code_map: dict = {}
    delist_url: Optional[str] = None
    lookup_url: Optional[str] = None
    rate_limit_qps: float = 5.0
    enabled: bool = True
    requires_key: bool = False
    api_key: Optional[str] = None


class BlacklistUpdate(BaseModel):
    name: Optional[str] = None
    zone: Optional[str] = None
    type: Optional[BLType] = None
    default_severity: Optional[Severity] = None
    return_code_map: Optional[dict] = None
    delist_url: Optional[str] = None
    lookup_url: Optional[str] = None
    rate_limit_qps: Optional[float] = None
    enabled: Optional[bool] = None
    requires_key: Optional[bool] = None
    api_key: Optional[str] = None


class BlacklistOut(ORMModel):
    id: int
    name: str
    zone: str
    type: BLType
    default_severity: Severity
    return_code_map: dict
    delist_url: Optional[str]
    lookup_url: Optional[str]
    rate_limit_qps: float
    enabled: bool
    requires_key: bool
    has_key: bool = False


# ---------- Listings ----------
class ListingOut(ORMModel):
    id: int
    ip_id: Optional[int]
    domain_id: Optional[int]
    blacklist_id: int
    sublist: Optional[str]
    severity: Severity
    detected_at: datetime
    removed_at: Optional[datetime]
    duration_minutes: Optional[int]
    txt_reason: Optional[str]
    status: ListingStatus
    ticket_ref: Optional[str]


class DelistRequest(BaseModel):
    requested_by: str


# ---------- Alert rules ----------
class AlertRuleCreate(BaseModel):
    name: str
    conditions: dict = {}
    channels: list = []
    escalation: dict = {}
    enabled: bool = True


class AlertRuleOut(ORMModel):
    id: int
    name: str
    conditions: dict
    channels: list
    escalation: dict
    enabled: bool
    created_at: datetime


# ---------- Settings ----------
class SettingsUpdate(BaseModel):
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: Optional[bool] = None
    smtp_from: Optional[str] = None
    pushover_app_token: Optional[str] = None
    spamhaus_dqs_key: Optional[str] = None
    dns_resolvers: Optional[str] = None
    default_check_interval_minutes: Optional[int] = None
    listed_ip_recheck_minutes: Optional[int] = None
    log_level: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None


# ---------- Dashboard ----------
class KPIOut(BaseModel):
    monitored_ips: int
    clean_ips: int
    clean_pct: float
    listed_ips: int
    listed_pct: float
    critical_listings: int
    critical_pct: float
    monitored_domains: int


class ActivityOut(ORMModel):
    id: int
    action: str
    entity: Optional[str]
    payload: dict
    created_at: datetime


# ---------- Maintenance ----------
class DBIssueOut(BaseModel):
    type: str
    id: int
    label: str
    detail: str


class DBCheckResult(BaseModel):
    issues: list[DBIssueOut]
    count: int


class DBCleanResult(BaseModel):
    removed_blocks: int
    fixed_ips: int
