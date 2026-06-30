from app.validator import TargetValidator, SecurityValidationError

validator = TargetValidator(allowlist_domains=["allowed-stand.local"])

def execute_scenario(scenario_name, func, *args):
    print(f"{scenario_name:<55} -> ", end="")
    try:
        result = func(*args)
        print(f"\033[92m{result}\033[0m")
    except SecurityValidationError as error:
        print(f"\033[91mОшибка: {error}\033[0m")

print("=" * 80)
print(" ВЕРИФИКАЦИЯ СИСТЕМЫ БЕЗОПАСНОСТИ")
print("=" * 80)

execute_scenario("1. Тест loopback адреса (IPv4 127.0.0.1)", validator.validate_target_url, "http://127.0.0.1:8080")
execute_scenario("2. Тест loopback адреса из подсети (IPv4 127.0.0.2)", validator.validate_target_url, "http://127.0.0.2:3000")
execute_scenario("3. Тест loopback адреса (IPv6 ::1)", validator.validate_target_url, "http://[::1]:8080")
execute_scenario("4. Тест loopback хоста (localhost)", validator.validate_target_url, "https://localhost/api")
execute_scenario("5. Тест разрешенного домена из Allowlist", validator.validate_target_url, "http://allowed-stand.local:9000")

execute_scenario("6. Тест URL без имени хоста (http:///path)", validator.validate_target_url, "http:///path")
execute_scenario("7. Тест несуществующего домена (ошибка DNS)", validator.validate_target_url, "http://non-existent-domain-xyz.local")

execute_scenario("8. Тест запрещенного протокола (file://)", validator.validate_target_url, "file:///etc/passwd")
execute_scenario("9. Тест запрещенного внешнего сайта (google.com)", validator.validate_target_url, "https://google.com")
execute_scenario("10. Тест безопасного относительного редиректа", validator.validate_redirect, "http://127.0.0.1:8080/login", "/dashboard")
execute_scenario("11. Тест опасного внешнего редиректа", validator.validate_redirect, "http://127.0.0.1:8080/login", "https://google.com/malicious")

print("=" * 80)