import pytest
from app.validator import TargetValidator, SecurityValidationError


@pytest.fixture
def validator():
    return TargetValidator(allowlist_domains=["allowed-stand.local"])


def test_loopback_allowed(validator):
    assert validator.validate_target_url("http://127.0.0.1:8080") is True
    assert validator.validate_target_url("https://localhost/api") is True


def test_allowed_domain(validator):
    assert validator.validate_target_url("http://allowed-stand.local:9000") is True


def test_forbidden_schema(validator):
    with pytest.raises(SecurityValidationError, match="Запрещенный протокол"):
        validator.validate_target_url("file:///etc/passwd")


def test_forbidden_domain(validator):
    with pytest.raises(SecurityValidationError, match="Обнаружен внешний IP-адрес"):
        validator.validate_target_url("https://google.com")


def test_safe_redirect(validator):
    current = "http://127.0.0.1:8080/login"
    redirect = "/dashboard"
    result = validator.validate_redirect(current, redirect)
    assert result == "http://127.0.0.1:8080/dashboard"


def test_external_redirect_forbidden(validator):
    current = "http://127.0.0.1:8080/login"
    external_redirect = "https://google.com/malicious"

    with pytest.raises(SecurityValidationError, match="Обнаружен внешний IP-адрес"):
        validator.validate_redirect(current, external_redirect)