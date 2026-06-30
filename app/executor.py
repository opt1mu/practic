import asyncio
import aiohttp
import yaml
import random
from validator import ScenarioModel, TargetValidator, SecurityValidationError
from pathlib import Path

async def execute_step(session: aiohttp.ClientSession, target: str, step):
    url = f"{target}{step.request.path}"
    method = step.request.method.upper()

    print(f"-> Выполняю {method} {url}")

    try:
        async with session.request(
                method=method,
                url=url,
                params=step.request.query,
                headers=step.request.headers,
                cookies=step.request.cookies,
                data=step.request.body  # Передаем JSON-строку как data
        ) as response:
            status = response.status

            if status in step.expect.status:
                print(f"   [OK] Статус {status}")
            else:
                print(f"   [ОШИБКА] Получен статус {status}")

    except Exception as e:
        print(f"   [СЕТЕВАЯ ОШИБКА] Не удалось выполнить запрос: {e}")

    pause_time = random.randint(step.pause_ms.min, step.pause_ms.max) / 1000.0
    print(f"   Пауза: {pause_time:.2f} сек...\n")
    await asyncio.sleep(pause_time)


async def run_scenario(file_path: str):
    with open(file_path, 'r', encoding='utf-8') as f:
        raw_data = yaml.safe_load(f)

    scenario = ScenarioModel(**raw_data)

    validator = TargetValidator(allowlist_domains=["127.0.0.1", "localhost"])
    try:
        validator.validate_target_url(scenario.target)
    except SecurityValidationError as e:
        print(f"Блокировка безопасности: {e}")
        return

    print(f"Сценарий '{scenario.name}' прошел валидацию. Начинаем выполнение...\n")

    async with aiohttp.ClientSession() as session:
        for step in scenario.steps:
            await execute_step(session, scenario.target, step)


if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent.parent
    scenario_path = BASE_DIR / "scenario.yaml"

    print(f"[*] Ищем конфигурацию по пути: {scenario_path}")
    asyncio.run(run_scenario(str(scenario_path)))