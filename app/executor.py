import asyncio
import aiohttp
import yaml
import random
import time
from collections import deque
from validator import ScenarioModel, TargetValidator, SecurityValidationError
from pydantic import ValidationError
from pathlib import Path

request_history = deque()


async def execute_step(session: aiohttp.ClientSession, target: str, step, client_id: int):
    url = f"{target}{step.request.path}"
    method = step.request.method.upper()

    try:
        async with session.request(
                method=method,
                url=url,
                params=step.request.query,
                headers=step.request.headers,
                cookies=step.request.cookies,
                data=step.request.body
        ) as response:
            request_history.append(time.time())
            status = response.status
            if status in step.expect.status:
                print(f"[Клиент {client_id}] [OK] {method} {step.request.path} | Статус {status}")
            else:
                print(f"[Клиент {client_id}] [ОШИБКА] {method} {step.request.path} | Статус {status}")
    except Exception as e:
        print(f"[Клиент {client_id}] [СЕТЕВАЯ ОШИБКА] {e}")


async def worker(client_id: int, scenario: ScenarioModel, session: aiohttp.ClientSession, rps_queue: asyncio.Queue,
                 stop_event: asyncio.Event):
    while not stop_event.is_set():
        for step in scenario.steps:
            if stop_event.is_set():
                break

            await rps_queue.get()

            await execute_step(session, scenario.target, step, client_id)

            pause_time = random.randint(step.pause_ms.min, step.pause_ms.max) / 1000.0
            print(f"[Клиент {client_id}] Пауза: {pause_time:.2f} сек.")  # Вот эта строка вернет логи
            await asyncio.sleep(pause_time)


async def rps_scheduler(rps_queue: asyncio.Queue, max_rps: int, duration: int, stop_event: asyncio.Event):
    start_time = time.time()
    interval = 1.0 / max_rps

    for i in range(1, int(duration * max_rps) + 1):
        if stop_event.is_set():
            break

        next_time = start_time + (i * interval)
        sleep_time = next_time - time.time()

        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

        if rps_queue.empty():
            await rps_queue.put(True)

    stop_event.set()


async def monitor_performance(duration: int):
    start_time = time.time()
    while (time.time() - start_time) < duration:
        await asyncio.sleep(1)
        now = time.time()
        while request_history and request_history[0] < now - 1:
            request_history.popleft()
        print("-"*50)
        print(f"[СТАТИСТИКА] Время: {int(now - start_time)}с | RPS: {len(request_history)}")
        print("-" * 50)

async def run_load_test(scenario_path: str):
    with open(scenario_path, 'r', encoding='utf-8') as f:
        scenario = ScenarioModel(**yaml.safe_load(f))

    validator = TargetValidator(allowlist_domains=["127.0.0.1", "localhost"])
    validator.validate_target_url(scenario.target)

    rps_queue = asyncio.Queue(maxsize=1)
    stop_event = asyncio.Event()

    async with aiohttp.ClientSession() as session:
        workers = [asyncio.create_task(worker(i, scenario, session, rps_queue, stop_event))
                   for i in range(1, scenario.limits.virtual_users + 1)]

        monitor = asyncio.create_task(monitor_performance(scenario.limits.duration_seconds))

        await rps_scheduler(rps_queue, scenario.limits.max_rps, scenario.limits.duration_seconds, stop_event)
        await asyncio.gather(*workers)
        monitor.cancel()

    print("[*] Тестирование завершено.")


if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent.parent
    scenario_path = BASE_DIR / "scenario.yaml"
    try:
        asyncio.run(run_load_test(str(scenario_path)))
    except KeyboardInterrupt:
        print("\n[!] Прервано пользователем.")