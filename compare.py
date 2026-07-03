import json
from pathlib import Path


def load_json(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def generate_report(base_path: str, protected_path: str):
    base = load_json(base_path)
    protected = load_json(protected_path)

    base_success = base["statuses"].get("200", 0) + base["statuses"].get("201", 0)
    base_429 = base["statuses"].get("429", 0)
    base_p95 = base["p95_ms"]
    base_errors = base["connection_errors"]

    prot_success = protected["statuses"].get("200", 0) + protected["statuses"].get("201", 0)
    prot_429 = protected["statuses"].get("429", 0)
    prot_p95 = protected["p95_ms"]
    prot_errors = protected["connection_errors"]

    diff_success = prot_success - base_success
    diff_429 = prot_429 - base_429
    diff_p95 = prot_p95 - base_p95
    diff_errors = prot_errors - base_errors

    w_metric = 18
    w_base = 14
    w_prot = 16
    w_diff = 8

    print(
        f"| {'Метрика':<{w_metric}} | {'Базовый запуск':<{w_base}} | {'Запуск с защитой':<{w_prot}} | {'Разница':<{w_diff}} |")
    print(f"| :{'-' * (w_metric - 1)} | :{'-' * (w_base - 1)} | :{'-' * (w_prot - 1)} | :{'-' * (w_diff - 1)} |")

    print(
        f"| {'Успешные запросы':<{w_metric}} | {base_success:<{w_base}} | {prot_success:<{w_prot}} | {f'{diff_success:+}':<{w_diff}} |")
    print(f"| {'Ответы 429':<{w_metric}} | {base_429:<{w_base}} | {prot_429:<{w_prot}} | {f'{diff_429:+}':<{w_diff}} |")
    print(
        f"| {'p95 (мс)':<{w_metric}} | {f'{base_p95:.2f}':<{w_base}} | {f'{prot_p95:.2f}':<{w_prot}} | {f'{diff_p95:+.2f}':<{w_diff}} |")
    print(
        f"| {'Ошибки':<{w_metric}} | {base_errors:<{w_base}} | {prot_errors:<{w_prot}} | {f'{diff_errors:+}':<{w_diff}} |")


if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent.parent
    base_path = BASE_DIR / "practic/summary_base.json"
    protected_path = BASE_DIR / "practic/summary_protected.json"
    generate_report(str(base_path), str(protected_path))