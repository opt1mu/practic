import socket
from urllib.parse import urlparse

class SecurityValidationError(Exception):
    # кастомный класс ошибки для фиксации нарушений безопасности
    pass

class TargetValidator:
    def __init__(self, allowlist_domains: list[str] = None):
        # сохранение списка локальных интерфейсов в коде
        self.loopback_ips = {"127.0.0.1", "::1", "localhost"}
        # преобразование белого списка доменов в множество для быстрого поиска
        self.allowlist_domains = set(allowlist_domains) if allowlist_domains else set()

    def is_loopback_ip(self, ip: str) -> bool:
        # проверка нахождения ip в локальном списке или принадлежности к сети 127.0.0.0/8
        return ip in self.loopback_ips or ip.startswith("127.")

    def resolve_dns(self, hostname: str) -> list[str]:
        try:
            # получение системной информации о сетевых адресах хоста
            addr_info = socket.getaddrinfo(hostname, None)
            # извлечение уникальных ip-адресов и преобразование их в список
            return list(set(info[4][0] for info in addr_info))
        except socket.gaierror:
            # вызов исключения безопасности, если dns-имя не удалось разрешить
            raise SecurityValidationError(f"Не удалось выполнить DNS-резолв для хоста: {hostname}")

    def validate_target_url(self, url: str) -> bool:
        # синтаксический разбор строки url на составляющие компоненты
        parsed_url = urlparse(url)

        # проверка используемого прикладного протокола
        if parsed_url.scheme not in ("http", "https"):
            raise SecurityValidationError(f"Запрещенный протокол: {parsed_url.scheme}. Разрешены только http и https.")

        # извлечение доменного имени или ip-адреса из структуры url
        hostname = parsed_url.hostname
        if not hostname:
            raise SecurityValidationError("Не удалось извлечь имя хоста из URL.")

        # допуск без проверки dns, если хост изначально находится в белом списке или локален
        if hostname in self.allowlist_domains or hostname in self.loopback_ips:
            return True

        # получение списка всех физических адресов через dns-запрос
        resolved_ips = self.resolve_dns(hostname)

        # поочередная проверка каждого ip-адреса из полученного списка
        for ip in resolved_ips:
            # пропуск проверки для локальных адресов компьютера
            if self.is_loopback_ip(ip):
                continue
            # блокировка, если найден внешний ip, а домен отсутствует в белом списке
            if hostname not in self.allowlist_domains:
                raise SecurityValidationError(
                    f"Обнаружен внешний IP-адрес {ip} для хоста {hostname}. Запуск заблокирован!"
                )

        return True

    def validate_redirect(self, current_url: str, redirect_url: str) -> str:
        # разбор адреса перенаправления
        parsed_redirect = urlparse(redirect_url)

        # обработка ситуации, если адрес редиректа является относительным путем
        if not parsed_redirect.scheme:
            # разбор текущего базового url для копирования его параметров
            parsed_current = urlparse(current_url)
            # сборка абсолютного пути из протокола и хоста текущего url и пути редиректа
            redirect_url = f"{parsed_current.scheme}://{parsed_current.netloc}{redirect_url}"

        # обязательный запуск сквозной проверки безопасности для полученного адреса редиректа
        self.validate_target_url(redirect_url)
        return redirect_url