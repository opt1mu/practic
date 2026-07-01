import asyncio
import aiohttp
import yaml
import random
from validator import ScenarioModel, TargetValidator, SecurityValidationError
from pydantic import ValidationError
from pathlib import Path

async def execute_step(session: aiohttp.ClientSession, target: str, step, client_id: int):
    url = f"{target}{step.request.path}"
    method = step.request.method.upper()

    print(f"[Клиент {client_id}] -> Выполняю {method} {url}")

    try:
        async with session.request(
                method=method,
                url=url,
                params=step.request.query,
                headers=step.request.headers,
                cookies=step.request.cookies,
                data=step.request.body
        ) as response:
            status = response.status

            if status in step.expect.status:
                print(f"[Клиент {client_id}]   [OK] Статус {status}")
            else:
                print(f"[Клиент {client_id}]   [ОШИБКА] Получен статус {status}")
            '''
            print(f"[Клиент {client_id}] Содержимое CookieJar:")
            if session.cookie_jar:
                for cookie in session.cookie_jar:
                    print(f"{cookie.key} = {cookie.value}")
            else:
                print("[CookieJar пуст]")
            '''
    except Exception as e:
        print(f"[Клиент {client_id}]   [СЕТЕВАЯ ОШИБКА] Не удалось выполнить запрос: {e}")

    pause_time = random.randint(step.pause_ms.min, step.pause_ms.max) / 1000.0
    print(f"[Клиент {client_id}]   Пауза: {pause_time:.2f} сек...\n")
    await asyncio.sleep(pause_time)


async def run_client(scenario: ScenarioModel, client_id: int):
    async with aiohttp.ClientSession() as session:
        for step in scenario.steps:
            await execute_step(session, scenario.target, step, client_id)


async def run_load_test(scenario_path: str):
    with open(scenario_path, 'r', encoding='utf-8') as f:
        raw_data = yaml.safe_load(f)

    try:
        scenario = ScenarioModel(**raw_data)
    except ValidationError as ve:
        print(f"[!] ОШИБКА ВАЛИДАЦИИ КОНФИГУРАЦИИ:\n{ve}")
        return

    validator = TargetValidator(allowlist_domains=["127.0.0.1", "localhost"])
    try:
        validator.validate_target_url(scenario.target)
    except SecurityValidationError as e:
        print(f"[!] Блокировка безопасности: {e}")
        return

    print(f"Сценарий '{scenario.name}' прошел валидацию. Начинаем выполнение...\n")

    num_users = scenario.limits.virtual_users
    print(f"[*] Запуск теста: {num_users} виртуальных пользователей (на основе scenario.yaml)...\n")

    tasks = [run_client(scenario, client_id) for client_id in range(1, num_users + 1)]

    await asyncio.gather(*tasks)
    print("[*] Нагрузочное тестирование завершено.")


if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent.parent
    scenario_path = BASE_DIR / "scenario.yaml"
    print(f"[*] Ищем конфигурацию по пути: {scenario_path}")

    try:
        asyncio.run(run_load_test(str(scenario_path)))
    except KeyboardInterrupt:
        print("\n[!] Тестирование прервано пользователем.")