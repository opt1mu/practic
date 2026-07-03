import asyncio
import aiohttp
import yaml
import random
import time
from collections import deque
from validator import ScenarioModel, TargetValidator, SecurityValidationError
from pathlib import Path
from metrics import MetricsCollector

request_history = deque()
total_requests = 0
error_requests = 0
status_429_count = 0
all_latencies = []


async def execute_step(session: aiohttp.ClientSession, target: str, step, client_id: int,
                       validator: TargetValidator, stop_event: asyncio.Event,
                       metrics_collector: MetricsCollector, scenario_id: str, context: dict):
    global total_requests, error_requests, status_429_count, all_latencies

    url = f"{target}{step.request.path}"
    method = step.request.method.upper()

    try:
        validator.validate_target_url(url)
    except SecurityValidationError as e:
        print(f"\n[KILL SWITCH] цель перестала проходить проверку allowlist: {e}")
        context["stop_reason"] = "security_violation"
        stop_event.set()
        return

    start_time = time.time()
    step_id = getattr(step, 'name', step.request.path)
    try:
        async with session.request(
                method=method,
                url=url,
                params=step.request.query,
                headers=step.request.headers,
                cookies=step.request.cookies,
                data=step.request.body
        ) as response:
            body = await response.read()
            bytes_received = len(body)
            redirects = len(response.history)

            latency = (time.time() - start_time) * 1000
            all_latencies.append(latency)
            request_history.append(time.time())
            total_requests += 1

            status = response.status

            if status == 429:
                status_429_count += 1

            if status in step.expect.status:
                print(f"[Клиент {client_id}] [OK] {method} {step.request.path} | Статус {status}")
            else:
                error_requests += 1
                print(f"[Клиент {client_id}] [ОШИБКА] {method} {step.request.path} | Статус {status}")

            metrics_collector.add_metric(
                scenario_id=scenario_id,
                step_id=step_id,
                status=status,
                latency_ms=latency,
                bytes_received=bytes_received,
                redirects=redirects,
                error=None
            )
    except Exception as e:
        total_requests += 1
        error_requests += 1
        print(f"[Клиент {client_id}] [СЕТЕВАЯ ОШИБКА] {e}")

        metrics_collector.add_metric(
            scenario_id=scenario_id,
            step_id=step_id,
            status=None,
            latency_ms=None,
            bytes_received=0,
            redirects=0,
            error=str(e)
        )


async def worker(client_id: int, scenario: ScenarioModel, session: aiohttp.ClientSession, rps_queue: asyncio.Queue,
                 stop_event: asyncio.Event, validator: TargetValidator, metrics_collector: MetricsCollector, context: dict):
    scenario_id = getattr(scenario, 'name', 'main_scenario')
    while not stop_event.is_set():
        for step in scenario.steps:
            if stop_event.is_set():
                break

            await rps_queue.get()

            if stop_event.is_set():
                break

            await execute_step(session, scenario.target, step, client_id, validator, stop_event, metrics_collector, scenario_id, context)

            pause_time = random.randint(step.pause_ms.min, step.pause_ms.max) / 1000.0
            print(f"[Клиент {client_id}] Пауза: {pause_time:.2f} сек.")
            await asyncio.sleep(pause_time)


async def rps_scheduler(rps_queue: asyncio.Queue, scenario: ScenarioModel, stop_event: asyncio.Event, context: dict):
    start_time = time.time()
    duration = scenario.limits.duration_seconds
    profile = scenario.load_profile
    max_limit = scenario.limits.max_rps

    next_token_time = time.time()

    while (time.time() - start_time) < duration:
        if stop_event.is_set():
            break

        elapsed = time.time() - start_time

        if profile.type == "stepped":
            step_duration = profile.step_duration_sec
            step_increase = profile.step_rps
            current_step = int(elapsed // step_duration)
            current_rps = min(step_increase + (current_step * step_increase), max_limit)
        elif profile.type == "spike":
            start = profile.spike_start_sec
            dur = profile.spike_duration_sec
            target = profile.spike_rps
            if start <= elapsed < (start + dur):
                current_rps = target
            else:
                current_rps = scenario.limits.max_rps
        else:
            current_rps = scenario.limits.max_rps

        interval = 1.0 / current_rps
        next_token_time += interval

        sleep_time = next_token_time - time.time()
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
        else:
            next_token_time = time.time()

        try:
            rps_queue.put_nowait(True)
        except asyncio.QueueFull:
            pass

    # если лимит времени теста вышел сам, фиксируем штатное окончание
    if not stop_event.is_set():
        context["stop_reason"] = "duration_limit"
        stop_event.set()


async def monitor_performance(scenario: ScenarioModel, stop_event: asyncio.Event, context: dict):
    global total_requests, error_requests, status_429_count, all_latencies
    start_time = time.time()

    while not stop_event.is_set():
        await asyncio.sleep(1)
        now = time.time()

        while request_history and request_history[0] < now - 1:
            request_history.popleft()

        current_rps = len(request_history)
        error_rate = (error_requests / total_requests * 100) if total_requests > 0 else 0.0

        p95 = 0.0
        if all_latencies:
            sorted_latencies = sorted(all_latencies)
            p95_index = int(len(sorted_latencies) * 0.95)
            if p95_index >= len(sorted_latencies):
                p95_index = len(sorted_latencies) - 1
            p95 = sorted_latencies[p95_index]

        print("-" * 50)
        print(f"[СТАТИСТИКА] Время: {int(now - start_time)}с | RPS: {current_rps} | Всего: {total_requests}")
        print("-" * 50)

        if total_requests >= scenario.limits.max_requests:
            print(f"\n[KILL SWITCH] достигнут лимит запросов: {total_requests}")
            context["stop_reason"] = "max_requests_limit"
            stop_event.set()
            break

        if total_requests >= 5 and error_rate >= scenario.stop_conditions.error_rate_percent:
            print(f"\n[KILL SWITCH] превышена доля ошибок: {error_rate:.1f}%")
            context["stop_reason"] = "error_rate_exceeded"
            stop_event.set()
            break

        if status_429_count >= scenario.stop_conditions.status_429_count:
            print(f"\n[KILL SWITCH] получено критическое число 429: {status_429_count}")
            context["stop_reason"] = "status_429_limit_exceeded"
            stop_event.set()
            break

        if total_requests >= 5 and p95 >= scenario.stop_conditions.p95_latency_ms:
            print(f"\n[KILL SWITCH] превышена p95-задержка: {p95:.1f}мс")
            context["stop_reason"] = "p95_latency_exceeded"
            stop_event.set()
            break


async def run_load_test(scenario_path: str):
    with open(scenario_path, 'r', encoding='utf-8') as f:
        scenario = ScenarioModel(**yaml.safe_load(f))

    validator = TargetValidator(allowlist_domains=["127.0.0.1", "localhost"])
    validator.validate_target_url(scenario.target)

    rps_queue = asyncio.Queue(maxsize=20)
    stop_event = asyncio.Event()

    context = {"stop_reason": "duration_limit"}

    metrics_collector = MetricsCollector(raw_log_path="raw_metrics.jsonl", summary_path="summary_metrics.json")
    await metrics_collector.start()

    workers = []
    monitor = None
    scheduler = None

    try:
        async with aiohttp.ClientSession() as session:
            workers = [asyncio.create_task(worker(i, scenario, session, rps_queue, stop_event, validator, metrics_collector, context))
                       for i in range(1, scenario.limits.virtual_users + 1)]

            monitor = asyncio.create_task(monitor_performance(scenario, stop_event, context))
            scheduler = asyncio.create_task(rps_scheduler(rps_queue, scenario, stop_event, context))

            await stop_event.wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        context["stop_reason"] = "keyboard_interrupt"
    finally:
        for w in workers:
            w.cancel()
        if monitor:
            monitor.cancel()
        if scheduler:
            scheduler.cancel()

        await asyncio.gather(*workers, monitor, scheduler, return_exceptions=True)
        # остановка фонового логирования и генерация финального json-отчета
        await metrics_collector.stop(context["stop_reason"])

    print("[*] Тестирование завершено.")


if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent.parent
    scenario_path = BASE_DIR / "scenario.yaml"
    try:
        asyncio.run(run_load_test(str(scenario_path)))
    except KeyboardInterrupt:
        print("\n[KILL SWITCH] получен сигнал пользователя (KeyboardInterrupt).")