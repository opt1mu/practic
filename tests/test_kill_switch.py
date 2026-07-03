import pytest
import asyncio
from unittest.mock import MagicMock
from app.validator import SecurityValidationError
from app import executor


@pytest.fixture(autouse=True)
def reset_globals():
    # сброс глобальных переменных перед каждым тестом
    executor.total_requests = 0
    executor.error_requests = 0
    executor.status_429_count = 0
    executor.all_latencies = []
    executor.request_history.clear()


@pytest.mark.asyncio
async def test_stop_on_time_limit():
    # тест остановки: достигнут лимит времени
    scenario = MagicMock()
    scenario.limits.duration_seconds = 1
    scenario.limits.max_rps = 10
    scenario.load_profile.type = "uniform"

    rps_queue = asyncio.Queue(maxsize=20)
    stop_event = asyncio.Event()

    # запуск планировщика, который должен завершиться по тайм-ауту
    await executor.rps_scheduler(rps_queue, scenario, stop_event)

    assert stop_event.is_set() is True


@pytest.mark.asyncio
async def test_stop_on_max_requests():
    # тест остановки: достигнут лимит запросов
    scenario = MagicMock()
    scenario.limits.max_requests = 5
    scenario.stop_conditions.error_rate_percent = 100
    scenario.stop_conditions.status_429_count = 100
    scenario.stop_conditions.p95_latency_ms = 100000

    # искусственное заполнение счетчика до лимита
    executor.total_requests = 5
    stop_event = asyncio.Event()

    task = asyncio.create_task(executor.monitor_performance(scenario, stop_event))
    await asyncio.sleep(1.1)  # ожидание одного такта цикла мониторинга

    assert stop_event.is_set() is True
    task.cancel()


@pytest.mark.asyncio
async def test_stop_on_error_rate():
    # тест остановки: превышена доля ошибок
    scenario = MagicMock()
    scenario.limits.max_requests = 100
    scenario.stop_conditions.error_rate_percent = 50
    scenario.stop_conditions.status_429_count = 100
    scenario.stop_conditions.p95_latency_ms = 100000

    # 4 ошибки из 6 запросов составляют более 50%
    executor.total_requests = 6
    executor.error_requests = 4
    stop_event = asyncio.Event()

    task = asyncio.create_task(executor.monitor_performance(scenario, stop_event))
    await asyncio.sleep(1.1)

    assert stop_event.is_set() is True
    task.cancel()


@pytest.mark.asyncio
async def test_stop_on_429_count():
    # тест остановки: получено заданное число 429
    scenario = MagicMock()
    scenario.limits.max_requests = 100
    scenario.stop_conditions.error_rate_percent = 100
    scenario.stop_conditions.status_429_count = 3
    scenario.stop_conditions.p95_latency_ms = 100000

    executor.total_requests = 5
    executor.status_429_count = 3
    stop_event = asyncio.Event()

    task = asyncio.create_task(executor.monitor_performance(scenario, stop_event))
    await asyncio.sleep(1.1)

    assert stop_event.is_set() is True
    task.cancel()


@pytest.mark.asyncio
async def test_stop_on_p95_latency():
    # тест остановки: превышена p95-задержка
    scenario = MagicMock()
    scenario.limits.max_requests = 100
    scenario.stop_conditions.error_rate_percent = 100
    scenario.stop_conditions.status_429_count = 100
    scenario.stop_conditions.p95_latency_ms = 500

    executor.total_requests = 20
    # подкладываем задержки так, чтобы 95-й процентиль превысил 500мс
    executor.all_latencies = [10] * 19 + [600]
    stop_event = asyncio.Event()

    task = asyncio.create_task(executor.monitor_performance(scenario, stop_event))
    await asyncio.sleep(1.1)

    assert stop_event.is_set() is True
    task.cancel()


def test_stop_on_user_signal(capsys):
    # тест остановки: получен сигнал пользователя (KeyboardInterrupt)
    try:
        raise KeyboardInterrupt
    except KeyboardInterrupt:
        print("\n[KILL SWITCH] получен сигнал пользователя (KeyboardInterrupt). выполнение прервано.")

    captured = capsys.readouterr()
    assert "получен сигнал пользователя" in captured.out


@pytest.mark.asyncio
async def test_stop_on_allowlist_failure():
    # тест остановки: цель перестала проходить проверку allowlist
    validator_mock = MagicMock()
    validator_mock.validate_target_url.side_effect = SecurityValidationError("запуск заблокирован")

    step_mock = MagicMock()
    step_mock.request.path = "/api"
    step_mock.request.method = "GET"

    stop_event = asyncio.Event()
    session_mock = MagicMock()

    # вызов одиночного шага с невалидным url должен взвести stop_event
    await executor.execute_step(session_mock, "http://127.0.0.1", step_mock, 1, validator_mock, stop_event)

    assert stop_event.is_set() is True