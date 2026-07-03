import asyncio
import json
import time
import os
from typing import Dict, List, Optional


class MetricsCollector:
    def __init__(self, raw_log_path: str, summary_path: str):
        self.raw_log_path = raw_log_path
        self.summary_path = summary_path
        self.queue = asyncio.Queue()
        self._logging_task: Optional[asyncio.Task] = None
        self._is_running = False
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.stop_reason = "unknown"

    async def start(self):
        # запуск фоновой задачи для потокобезопасного логирования сырых событий
        self.start_time = time.time()
        self._is_running = True
        self._logging_task = asyncio.create_task(self._write_loop())

    async def _write_loop(self):
        # асинцикл чтения очереди и последовательной записи строк в jsonl
        with open(self.raw_log_path, 'w', encoding='utf-8') as f:
            while self._is_running or not self.queue.empty():
                try:
                    # ожидание записи из очереди с таймаутом, чтобы не блокировать завершение
                    record = await asyncio.wait_for(self.queue.get(), timeout=0.1)
                    f.write(json.dumps(record) + '\n')
                    self.queue.task_done()
                except asyncio.TimeoutError:
                    continue

    def add_metric(self, scenario_id: str, step_id: str, status: Optional[int],
                   latency_ms: Optional[float], bytes_received: int,
                   redirects: int, error: Optional[str] = None):
        # неблокирующее добавление метрики из асинхронного воркера в очередь
        record = {
            "timestamp": time.time(),
            "scenario_id": scenario_id,
            "step_id": step_id,
            "status": status,
            "latency_ms": latency_ms,
            "bytes": bytes_received,
            "redirects": redirects,
            "error": error
        }
        self.queue.put_nowait(record)

    async def stop(self, stop_reason: str):
        # штатная остановка логирования, очистка очереди и запуск агрегации отчета
        self.stop_reason = stop_reason
        self.end_time = time.time()
        self._is_running = False

        if self._logging_task:
            # ожидание обработки всех оставшихся в очереди записей
            await self.queue.join()
            await self._logging_task

        self._generate_summary()

    def _calculate_percentiles(self, latencies: List[float]) -> Dict[str, float]:
        # расчет процентилей p50, p95 и p99 для списка задержек
        if not latencies:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}

        sorted_latencies = sorted(latencies)
        n = len(sorted_latencies)

        return {
            "p50": round(sorted_latencies[int(n * 0.50)], 2),
            "p95": round(sorted_latencies[int(n * 0.95)] if int(n * 0.95) < n else sorted_latencies[-1], 2),
            "p99": round(sorted_latencies[int(n * 0.99)] if int(n * 0.99) < n else sorted_latencies[-1], 2)
        }

    def _generate_summary(self):
        # чтение сохраненного jsonl файла и расчет агрегированных метрик для json отчета
        if not os.path.exists(self.raw_log_path):
            return

        total_requests = 0
        total_bytes = 0
        total_redirects = 0
        error_count = 0
        statuses: Dict[str, int] = {}
        all_latencies: List[float] = []

        # структура для раздельного сбора метрик по сценариям и шагам
        scenarios_data = {}

        with open(self.raw_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)

                total_requests += 1
                total_bytes += data["bytes"]
                total_redirects += data["redirects"]

                if data["error"]:
                    error_count += 1

                status_str = str(data["status"]) if data["status"] else "connection_error"
                statuses[status_str] = statuses.get(status_str, 0) + 1

                if data["latency_ms"] is not None:
                    all_latencies.append(data["latency_ms"])

                scen_id = data["scenario_id"]
                step_id = data["step_id"]

                # инициализация структуры сценария
                if scen_id not in scenarios_data:
                    scenarios_data[scen_id] = {
                        "total_requests": 0, "bytes": 0, "redirects": 0,
                        "errors": 0, "statuses": {}, "latencies": [], "steps": {}
                    }

                s_data = scenarios_data[scen_id]
                s_data["total_requests"] += 1
                s_data["bytes"] += data["bytes"]
                s_data["redirects"] += data["redirects"]
                if data["error"]:
                    s_data["errors"] += 1
                s_data["statuses"][status_str] = s_data["statuses"].get(status_str, 0) + 1
                if data["latency_ms"] is not None:
                    s_data["latencies"].append(data["latency_ms"])

                # инициализация структуры шага внутри сценария
                if step_id not in s_data["steps"]:
                    s_data["steps"][step_id] = {
                        "total_requests": 0, "bytes": 0, "redirects": 0,
                        "errors": 0, "statuses": {}, "latencies": []
                    }

                st_data = s_data["steps"][step_id]
                st_data["total_requests"] += 1
                st_data["bytes"] += data["bytes"]
                st_data["redirects"] += data["redirects"]
                if data["error"]:
                    st_data["errors"] += 1
                st_data["statuses"][status_str] = st_data["statuses"].get(status_str, 0) + 1
                if data["latency_ms"] is not None:
                    st_data["latencies"].append(data["latency_ms"])

        # расчет общей продолжительности теста и rps
        duration = (self.end_time - self.start_time) if self.start_time and self.end_time else 1.0
        if duration <= 0:
            duration = 0.001

        total_rps = total_requests / duration
        global_percentiles = self._calculate_percentiles(all_latencies)

        # формирование финального словаря в соответствии с требованиями
        summary = {
            "total_requests": total_requests,
            "total_rps": round(total_rps, 2),
            "total_bytes_received": total_bytes,
            "total_redirects": total_redirects,
            "connection_errors": error_count,
            "statuses": statuses,
            "p50_ms": global_percentiles["p50"],
            "p95_ms": global_percentiles["p95"],
            "p99_ms": global_percentiles["p99"],
            "stop_reason": self.stop_reason,
            "duration_seconds": round(duration, 2),
            "scenarios": {}
        }

        # наполнение детализации по каждому сценарию и его шагам
        for scen_id, s_data in scenarios_data.items():
            scen_perc = self._calculate_percentiles(s_data["latencies"])
            scen_rps = s_data["total_requests"] / duration

            summary["scenarios"][scen_id] = {
                "total_requests": s_data["total_requests"],
                "rps": round(scen_rps, 2),
                "connection_errors": s_data["errors"],
                "statuses": s_data["statuses"],
                "p50_ms": scen_perc["p50"],
                "p95_ms": scen_perc["p95"],
                "p99_ms": scen_perc["p99"],
                "steps": {}
            }

            for step_id, st_data in s_data["steps"].items():
                step_perc = self._calculate_percentiles(st_data["latencies"])
                step_rps = st_data["total_requests"] / duration

                summary["scenarios"][scen_id]["steps"][step_id] = {
                    "total_requests": st_data["total_requests"],
                    "rps": round(step_rps, 2),
                    "connection_errors": st_data["errors"],
                    "statuses": st_data["statuses"],
                    "p50_ms": step_perc["p50"],
                    "p95_ms": step_perc["p95"],
                    "p99_ms": step_perc["p99"]
                }

        # сохранение сводного отчета в файл json
        with open(self.summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=4, ensure_ascii=False)