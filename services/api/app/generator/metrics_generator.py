from datetime import datetime
from random import Random

from app.schemas.events import MetricPoint
from .config import SERVICE_CONFIGS, ServiceConfig


class MetricWalkState:
    """Maintains continuous autocorrelated random walk state for a single metric stream."""

    def __init__(self, baseline: float, step_stddev: float, min_val: float, max_val: float, reversion_speed: float = 0.15):
        self.baseline = baseline
        self.current = baseline
        self.step_stddev = step_stddev
        self.min_val = min_val
        self.max_val = max_val
        self.reversion_speed = reversion_speed

    def step(self, rng: Random) -> float:
        # Mean-reverting Ornstein-Uhlenbeck style discrete step
        drift = self.reversion_speed * (self.baseline - self.current)
        shock = rng.gauss(0.0, self.step_stddev)
        self.current = max(self.min_val, min(self.max_val, self.current + drift + shock))
        return self.current


def generate_healthy_metrics(
    service: str,
    window: list[datetime],
    rng: Random,
) -> list[MetricPoint]:
    """Generates an autocorrelated time series of healthy performance metrics for a service."""
    config = SERVICE_CONFIGS.get(
        service,
        ServiceConfig(name=service, description="Service", owns_database=False),
    )

    # Initialize metric random walkers around service baseline
    req_rate_walker = MetricWalkState(
        baseline=config.baseline_rps,
        step_stddev=config.baseline_rps * 0.05,
        min_val=max(1.0, config.baseline_rps * 0.4),
        max_val=config.baseline_rps * 1.8,
    )
    p50_walker = MetricWalkState(
        baseline=config.latency_p50_ms,
        step_stddev=config.latency_stddev_ms * 0.25,
        min_val=max(1.0, config.latency_p50_ms * 0.5),
        max_val=config.latency_p50_ms * 2.0,
    )
    p95_walker = MetricWalkState(
        baseline=config.latency_p95_ms,
        step_stddev=config.latency_stddev_ms * 0.5,
        min_val=config.latency_p50_ms * 1.1,
        max_val=config.latency_p95_ms * 2.5,
    )
    error_rate_walker = MetricWalkState(
        baseline=config.baseline_error_rate * 100.0,  # in percent (e.g. 0.2%)
        step_stddev=0.03,
        min_val=0.0,
        max_val=1.5,
    )
    cpu_walker = MetricWalkState(
        baseline=config.baseline_cpu_percent,
        step_stddev=1.8,
        min_val=10.0,
        max_val=80.0,
    )
    mem_walker = MetricWalkState(
        baseline=config.baseline_memory_mb,
        step_stddev=8.0,
        min_val=config.baseline_memory_mb * 0.7,
        max_val=config.baseline_memory_mb * 1.4,
    )

    if config.owns_database:
        db_conn_walker = MetricWalkState(
            baseline=float(config.baseline_db_connections),
            step_stddev=1.2,
            min_val=5.0,
            max_val=float(config.max_db_connections - 15),
        )

    metrics: list[MetricPoint] = []
    base_labels = {"service": service, "env": "production"}

    for ts in window:
        # 1. Request rate
        metrics.append(
            MetricPoint(
                timestamp=ts,
                service=service,
                metric_name="request_rate",
                value=round(req_rate_walker.step(rng), 2),
                unit="req/s",
                labels=base_labels,
            )
        )
        # 2. Latency p50
        p50_val = round(p50_walker.step(rng), 2)
        metrics.append(
            MetricPoint(
                timestamp=ts,
                service=service,
                metric_name="latency_p50_ms",
                value=p50_val,
                unit="ms",
                labels=base_labels,
            )
        )
        # 3. Latency p95 (ensure p95 >= p50)
        p95_val = round(max(p50_val * 1.05, p95_walker.step(rng)), 2)
        metrics.append(
            MetricPoint(
                timestamp=ts,
                service=service,
                metric_name="latency_p95_ms",
                value=p95_val,
                unit="ms",
                labels=base_labels,
            )
        )
        # 4. Error rate
        metrics.append(
            MetricPoint(
                timestamp=ts,
                service=service,
                metric_name="error_rate",
                value=round(error_rate_walker.step(rng), 4),
                unit="percent",
                labels=base_labels,
            )
        )
        # 5. CPU percent
        metrics.append(
            MetricPoint(
                timestamp=ts,
                service=service,
                metric_name="cpu_percent",
                value=round(cpu_walker.step(rng), 2),
                unit="percent",
                labels=base_labels,
            )
        )
        # 6. Memory MB
        metrics.append(
            MetricPoint(
                timestamp=ts,
                service=service,
                metric_name="memory_mb",
                value=round(mem_walker.step(rng), 2),
                unit="mb",
                labels=base_labels,
            )
        )
        # 7 & 8. Database metrics if service owns DB
        if config.owns_database:
            active_conn = round(db_conn_walker.step(rng), 1)
            metrics.append(
                MetricPoint(
                    timestamp=ts,
                    service=service,
                    metric_name="db_connections_active",
                    value=active_conn,
                    unit="count",
                    labels={**base_labels, "database": config.database_name or "db"},
                )
            )
            metrics.append(
                MetricPoint(
                    timestamp=ts,
                    service=service,
                    metric_name="db_connections_max",
                    value=float(config.max_db_connections),
                    unit="count",
                    labels={**base_labels, "database": config.database_name or "db"},
                )
            )

    return metrics
