import socket
from urllib.parse import urlparse
from typing import Dict, List, Optional, Literal
from pydantic import BaseModel, Field, model_validator

class SecurityValidationError(Exception):
    pass

class TargetValidator:
    def __init__(self, allowlist_domains: list[str] = None):
        self.loopback_ips = {"127.0.0.1", "::1", "localhost"}
        self.allowlist_domains = set(allowlist_domains) if allowlist_domains else set()

    def is_loopback_ip(self, ip: str) -> bool:
        return ip in self.loopback_ips or ip.startswith("127.")

    def resolve_dns(self, hostname: str) -> list[str]:
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            return list(set(info[4][0] for info in addr_info))
        except socket.gaierror:
            raise SecurityValidationError(
                f"Хост '{hostname}' не входит в контур разрешенных локальных доменов или не удалось выполнить его DNS-резолв. Внешний домен запрещен."
            )

    def validate_target_url(self, url: str) -> bool:
        parsed_url = urlparse(url)

        if parsed_url.scheme not in ("http", "https"):
            raise SecurityValidationError(f"Запрещенный протокол: {parsed_url.scheme}. Разрешены только http и https.")

        hostname = parsed_url.hostname
        if not hostname:
            raise SecurityValidationError("Не удалось извлечь имя хоста из URL.")

        if hostname in self.allowlist_domains or hostname in self.loopback_ips:
            return True

        resolved_ips = self.resolve_dns(hostname)

        for ip in resolved_ips:
            if self.is_loopback_ip(ip):
                continue
            if hostname not in self.allowlist_domains:
                raise SecurityValidationError(
                    f"Обнаружен внешний IP-адрес {ip} для хоста {hostname}. Запуск заблокирован!"
                )

        return True

    def validate_redirect(self, current_url: str, redirect_url: str) -> str:
        parsed_redirect = urlparse(redirect_url)

        if not parsed_redirect.scheme:
            parsed_current = urlparse(current_url)
            redirect_url = f"{parsed_current.scheme}://{parsed_current.netloc}{redirect_url}"

        self.validate_target_url(redirect_url)
        return redirect_url

class PauseModel(BaseModel):
    min: int = Field(..., ge=0)
    max: int = Field(..., ge=0)

class ExpectModel(BaseModel):
    status: List[int] = Field(default=[200])

class RequestModel(BaseModel):
    method: str = Field(default="GET")
    path: str
    query: Optional[Dict[str, str]] = None
    headers: Optional[Dict[str, str]] = None
    cookies: Optional[Dict[str, str]] = None
    body: Optional[str] = None

    @model_validator(mode='after')
    def validate_get_body(self) -> 'RequestModel':
        if self.method.upper() == "GET" and self.body is not None:
            raise ValueError("Метод GET не может содержать body.")
        return self

    @model_validator(mode='after')
    def validate_external_path(self) -> 'RequestModel':
        if self.path.startswith(("http://", "https://")):
            parsed = urlparse(self.path)
            hostname = parsed.hostname
            if hostname not in ("127.0.0.1", "::1", "localhost"):
                raise ValueError(f"В пути запроса шага обнаружен запрещенный внешний URL: {hostname}")
        return self

class StepModel(BaseModel):
    request: RequestModel
    expect: ExpectModel = Field(default_factory=ExpectModel)
    pause_ms: PauseModel

class LimitsModel(BaseModel):
    duration_seconds: int = Field(..., gt=0)
    max_requests: int = Field(..., gt=0)
    max_rps: int = Field(..., gt=0, le=20)
    virtual_users: int = Field(..., gt=0, le=20)

class StopConditionsModel(BaseModel):
    error_rate_percent: int
    status_429_count: int
    p95_latency_ms: int

class LoadProfileModel(BaseModel):
    type: Literal["uniform", "stepped", "spike"]
    step_duration_sec: Optional[int] = None
    step_rps: Optional[int] = None
    spike_start_sec: Optional[int] = None
    spike_duration_sec: Optional[int] = None
    spike_rps: Optional[int] = None

class ScenarioModel(BaseModel):
    name: str
    target: str
    load_profile: LoadProfileModel
    limits: LimitsModel
    stop_conditions: StopConditionsModel
    steps: List[StepModel]