import argparse
import asyncio
import sys
import os
import signal
import json
import yaml
import socket
from urllib.parse import urlparse
from pathlib import Path

from validator import ScenarioModel, TargetValidator
from executor import run_load_test

PID_FILE = Path(".traffic-gen.pid")


def load_and_validate(scenario_path: Path) -> ScenarioModel:
    if not scenario_path.exists():
        print(f"[ОШИБКА] Файл сценария не найден по пути: {scenario_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(scenario_path, 'r', encoding='utf-8') as f:
            raw_yaml = yaml.safe_load(f)
            scenario = ScenarioModel(**raw_yaml)
        print("[OK] Структура YAML-файла успешно валидирована через Pydantic.")

        validator = TargetValidator(allowlist_domains=["127.0.0.1", "localhost"])
        validator.validate_target_url(scenario.target)
        print(f"[OK] Проверка безопасности цели пройдена. Хост '{scenario.target}' разрешен.")
        return scenario
    except Exception as e:
        print(f"\n[ОШИБКА ВАЛИДАЦИИ] Конфигурация не прошла проверку:\n-> {e}", file=sys.stderr)
        sys.exit(1)


def cmd_validate(args):
    scenario_path = Path(args.scenario)
    print(f"[*] Запуск быстрой валидации для: {scenario_path}")
    load_and_validate(scenario_path)
    print("[*] Проверка завершена успешно. Ошибок не обнаружено.")


def cmd_dry_run(args):
    scenario_path = Path(args.scenario)
    print(f"[DRY-RUN] Запуск утилиты в режиме холостой проверки для: {scenario_path}")

    scenario = load_and_validate(scenario_path)

    try:
        parsed_url = urlparse(scenario.target)
        hostname = parsed_url.hostname
        if hostname:
            dns_info = f"{hostname} -> {socket.gethostbyname(hostname)}"
        else:
            dns_info = "Не удалось извлечь хост"
    except Exception as e:
        dns_info = f"Ошибка DNS ({e})"

    duration = scenario.limits.duration_seconds
    max_rps = scenario.limits.max_rps
    max_requests = scenario.limits.max_requests
    profile_type = scenario.load_profile.type

    if profile_type == "uniform":
        expected_requests = max_rps * duration
    elif profile_type == "stepped":
        expected_requests = int((max_rps * 0.7) * duration)
    elif profile_type == "spike":
        expected_requests = int((max_rps * 0.35) * duration)
    else:
        expected_requests = max_rps * duration

    is_capped = False
    if max_requests and expected_requests > max_requests:
        expected_requests = max_requests
        is_capped = True

    print("\n" + "=" * 65)
    print(f" СВОДКА СЦЕНАРИЯ:            {scenario.name}")
    print("=" * 65)
    print("[LIMITS]")
    print(f"  Профиль нагрузки:           {profile_type}")
    print(f"  Виртуальные клиенты:        {scenario.limits.virtual_users}")
    print(f"  Максимальный RPS:           {max_rps} req/sec")
    print(f"  Длительность теста:         {duration} сек.")
    print(f"  Жесткий лимит запросов:     {max_requests if max_requests else 'Отсутствует'}")
    print("\n[СЕТЕВАЯ ИНФРАСТРУКТУРА И DNS]")
    print(f"  Базовый URL цели:           {scenario.target}")
    print(f"  Разрешение DNS:             {dns_info}")

    global_redirect = getattr(scenario, "allow_redirects", True)
    print(f"  Redirects: {'Автоматическое следование' if global_redirect else 'Отключено'}")
    print("\n[ЦЕЛИ И МАРШРУТЫ ТЕСТИРОВАНИЯ]")

    if hasattr(scenario, 'steps') and scenario.steps:
        print(f"  Обнаружено шагов в сценарии: {len(scenario.steps)}")
        for idx, step in enumerate(scenario.steps, 1):
            req = getattr(step, 'request', None)
            if req:
                method = getattr(req, 'method', 'GET')
                path = getattr(req, 'path', '/')
                step_redirect = getattr(req, 'allow_redirects', global_redirect)
            else:
                method = getattr(step, 'method', 'GET')
                path = getattr(step, 'path', '/')
                step_redirect = getattr(step, 'allow_redirects', global_redirect)

            redir_status = "" if step_redirect == global_redirect else f" [Редирект: {step_redirect}]"
            print(f"    - Цель {idx}: {method:<6} {scenario.target.rstrip('/')}{path}{redir_status}")
    else:
        print(f"  - Специфичные шаги не заданы. Тестируется корень: {scenario.target}")

    print("\n[ПРОГНОЗ РАСЧЕТА НАГРУЗКИ]")
    cap_notice = " (ОГРАНИЧЕНО лимитом max_requests)" if is_capped else ""
    print(f"  Ожидаемое число запросов:   ~{expected_requests}{cap_notice}")
    print("=" * 65)
    print("\n[DRY-RUN] Тест полностью готов к безопасному запуску.")


def cmd_run(args):
    scenario_path = Path(args.scenario)
    print(f"[*] Инициализация нагрузочного теста по сценарию: {scenario_path}")
    PID_FILE.write_text(str(os.getpid()))

    try:
        asyncio.run(run_load_test(str(scenario_path)))
    except KeyboardInterrupt:
        print("\n[KILL SWITCH] Получен аварийный сигнал от пользователя (KeyboardInterrupt). Выход.")
    except Exception as e:
        print(f"[ОШИБКА СТАРТА] Не удалось запустить тест: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if PID_FILE.exists():
            PID_FILE.unlink()


def cmd_stop(args):
    print("[*] Поиск активных процессов генерации трафика...")

    if not PID_FILE.exists():
        print("[!] Активных процессов генератора трафика не обнаружено.")
        return

    try:
        pid = int(PID_FILE.read_text().strip())
        print(f"[*] Найден запущенный тест с PID: {pid}. Отправка сигнала остановки...")

        if sys.platform == "win32":
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGINT)

        print("[OK] Сигнал на остановку успешно отправлен. Генерация трафика прекращена.")
    except ProcessLookupError:
        print("[!] Процесс с указанным PID уже завершился. Очищаю устаревшие файлы конфигурации...")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось остановить процесс: {e}", file=sys.stderr)
    finally:
        if PID_FILE.exists():
            PID_FILE.unlink()


def cmd_compare(args):
    file_a = Path(args.report_a)
    file_b = Path(args.report_b)

    if not file_a.exists() or not file_b.exists():
        print(f"[ОШИБКА] Один или оба файла отчетов не найдены:\n-> {file_a}\n-> {file_b}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(file_a, 'r', encoding='utf-8') as f:
            data_a = json.load(f)
        with open(file_b, 'r', encoding='utf-8') as f:
            data_b = json.load(f)

        def extract_metrics(data):
            statuses = data.get("statuses", {})
            success = statuses.get("200", 0) + statuses.get("201", 0)
            errors_429 = statuses.get("429", 0)
            return {
                "total": data.get("total_requests", 0),
                "success": success,
                "429": errors_429,
                "rps": data.get("total_rps", 0.0),
                "p95": data.get("p95_ms", 0.0),
                "errors": data.get("connection_errors", 0)
            }

        m_a = extract_metrics(data_a)
        m_b = extract_metrics(data_b)

        print(f"\n[*] Сравнение результатов тестирования:")
        print(f"Тест А:   {file_a.name}")
        print(f"Тест Б:   {file_b.name}")

        w_metric, w_a, w_b, w_diff = 22, 14, 16, 10

        print("=" * 72)
        print(f"| {'Метрика':<{w_metric}} | {'Тест А':<{w_a}} | {'Тест Б':<{w_b}} | {'Разница':<{w_diff}} |")
        print(f"|:{'-' * (w_metric)} |:{'-' * (w_a)} |:{'-' * (w_b)} |:{'-' * (w_diff)} |")

        metrics_config = [
            ("total", "Всего запросов", "{:<14d}", "{:<16d}", "{:+}"),
            ("success", "Успешные запросы", "{:<14d}", "{:<16d}", "{:+}"),
            ("429", "Ответы 429", "{:<14d}", "{:<16d}", "{:+}"),
            ("rps", "Средний RPS", "{:<14.2f}", "{:<16.2f}", "{:+.2f}"),
            ("p95", "p95 задержка (мс)", "{:<14.2f}", "{:<16.2f}", "{:+.2f}"),
            ("errors", "Сетевые ошибки", "{:<14d}", "{:<16d}", "{:+}")
        ]

        for key, label, fmt_a, fmt_b, fmt_diff in metrics_config:
            val_a = m_a[key]
            val_b = m_b[key]
            diff = val_b - val_a

            diff_str = fmt_diff.format(diff) if diff != 0 else "0"
            str_a = fmt_a.format(val_a).strip()
            str_b = fmt_b.format(val_b).strip()

            print(f"| {label:<{w_metric}} | {str_a:<{w_a}} | {str_b:<{w_b}} | {diff_str:<{w_diff}} |")

        print("=" * 72)

    except json.JSONDecodeError:
        print("[ОШИБКА] Файлы отчетов должны быть валидными JSON-файлами.", file=sys.stderr)
    except Exception as e:
        print(f"[ОШИБКА СРАВНЕНИЯ] Произошел сбой: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        prog="traffic-gen",
        description="Безопасный асинхронный генератор тестового HTTP-трафика."
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        help="Доступные команды управления системой"
    )

    parser_validate = subparsers.add_parser("validate", help="Проверить синтаксис YAML и безопасность target")
    parser_validate.add_argument("scenario", type=str, help="Путь к YAML-файлу сценария")
    parser_validate.set_defaults(func=cmd_validate)

    parser_dry = subparsers.add_parser("dry-run", help="Имитация запуска со сводкой параметров без отправки запросов")
    parser_dry.add_argument("scenario", type=str, help="Путь к YAML-файлу сценария")
    parser_dry.set_defaults(func=cmd_dry_run)

    parser_run = subparsers.add_parser("run", help="Запустить генерацию боевой нагрузки")
    parser_run.add_argument("scenario", type=str, help="Путь к YAML-файлу сценария")
    parser_run.set_defaults(func=cmd_run)

    parser_stop = subparsers.add_parser("stop", help="Экстренно остановить текущие процессы тестирования")
    parser_stop.set_defaults(func=cmd_stop)

    parser_compare = subparsers.add_parser("compare", help="Сравнить метрики и отчеты прошлых запусков")
    parser_compare.add_argument("report_a", type=str, help="Путь к первому JSON-отчету (Тест А)")
    parser_compare.add_argument("report_b", type=str, help="Путь ко второму JSON-отчету (Тест Б)")
    parser_compare.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()