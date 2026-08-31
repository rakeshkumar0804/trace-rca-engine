from dataclasses import dataclass, field
from app.schemas.services import ServiceDefinition, ServiceDependency


@dataclass(frozen=True)
class ServiceConfig:
    """Baseline operational parameters and characteristics for a simulated microservice."""
    name: str
    description: str
    owns_database: bool
    database_name: str | None = None
    baseline_rps: float = 20.0
    latency_p50_ms: float = 25.0
    latency_p95_ms: float = 65.0
    latency_stddev_ms: float = 10.0
    baseline_error_rate: float = 0.002
    max_db_connections: int = 100
    baseline_db_connections: int = 25
    baseline_cpu_percent: float = 35.0
    baseline_memory_mb: float = 768.0


# 7 simulated services in the target architecture
SERVICE_CONFIGS: dict[str, ServiceConfig] = {
    "api-gateway": ServiceConfig(
        name="api-gateway",
        description="Public API gateway routing external requests to backend services",
        owns_database=False,
        baseline_rps=60.0,
        latency_p50_ms=12.0,
        latency_p95_ms=35.0,
        latency_stddev_ms=5.0,
        baseline_error_rate=0.001,
        baseline_cpu_percent=40.0,
        baseline_memory_mb=512.0,
    ),
    "auth-service": ServiceConfig(
        name="auth-service",
        description="Authentication and JWT token validation service",
        owns_database=False,
        baseline_rps=40.0,
        latency_p50_ms=8.0,
        latency_p95_ms=20.0,
        latency_stddev_ms=3.0,
        baseline_error_rate=0.001,
        baseline_cpu_percent=30.0,
        baseline_memory_mb=384.0,
    ),
    "checkout-service": ServiceConfig(
        name="checkout-service",
        description="Coordinates customer checkout flow, inventory reservations, and payment processing",
        owns_database=True,
        database_name="checkout_db",
        baseline_rps=25.0,
        latency_p50_ms=45.0,
        latency_p95_ms=110.0,
        latency_stddev_ms=15.0,
        baseline_error_rate=0.002,
        max_db_connections=100,
        baseline_db_connections=28,
        baseline_cpu_percent=45.0,
        baseline_memory_mb=1024.0,
    ),
    "order-service": ServiceConfig(
        name="order-service",
        description="Manages order creation, order state machine, and persistence",
        owns_database=True,
        database_name="order_db",
        baseline_rps=20.0,
        latency_p50_ms=30.0,
        latency_p95_ms=75.0,
        latency_stddev_ms=12.0,
        baseline_error_rate=0.002,
        max_db_connections=100,
        baseline_db_connections=22,
        baseline_cpu_percent=38.0,
        baseline_memory_mb=896.0,
    ),
    "payment-service": ServiceConfig(
        name="payment-service",
        description="Integrates with external payment gateways and records transactions",
        owns_database=True,
        database_name="payment_db",
        baseline_rps=18.0,
        latency_p50_ms=85.0,
        latency_p95_ms=190.0,
        latency_stddev_ms=25.0,
        baseline_error_rate=0.003,
        max_db_connections=80,
        baseline_db_connections=18,
        baseline_cpu_percent=32.0,
        baseline_memory_mb=768.0,
    ),
    "inventory-service": ServiceConfig(
        name="inventory-service",
        description="Tracks catalog item availability and item reservations",
        owns_database=False,
        baseline_rps=25.0,
        latency_p50_ms=15.0,
        latency_p95_ms=40.0,
        latency_stddev_ms=6.0,
        baseline_error_rate=0.001,
        baseline_cpu_percent=28.0,
        baseline_memory_mb=512.0,
    ),
    "notification-service": ServiceConfig(
        name="notification-service",
        description="Dispatches email, SMS, and webhook notifications asynchronously",
        owns_database=False,
        baseline_rps=15.0,
        latency_p50_ms=20.0,
        latency_p95_ms=50.0,
        latency_stddev_ms=8.0,
        baseline_error_rate=0.002,
        baseline_cpu_percent=25.0,
        baseline_memory_mb=384.0,
    ),
}

# Fixed topology dependencies
SERVICE_TOPOLOGY: list[ServiceDependency] = [
    ServiceDependency(
        from_service="api-gateway",
        to_service="auth-service",
        protocol="grpc",
        request_type="rpc",
        expected_latency_ms=8.0,
        dependency_strength="hard",
    ),
    ServiceDependency(
        from_service="api-gateway",
        to_service="checkout-service",
        protocol="http",
        request_type="rest",
        expected_latency_ms=45.0,
        dependency_strength="hard",
    ),
    ServiceDependency(
        from_service="checkout-service",
        to_service="order-service",
        protocol="grpc",
        request_type="rpc",
        expected_latency_ms=30.0,
        dependency_strength="hard",
    ),
    ServiceDependency(
        from_service="checkout-service",
        to_service="payment-service",
        protocol="http",
        request_type="rest",
        expected_latency_ms=85.0,
        dependency_strength="hard",
    ),
    ServiceDependency(
        from_service="checkout-service",
        to_service="inventory-service",
        protocol="grpc",
        request_type="rpc",
        expected_latency_ms=15.0,
        dependency_strength="hard",
    ),
    ServiceDependency(
        from_service="order-service",
        to_service="notification-service",
        protocol="http",
        request_type="rest",
        expected_latency_ms=20.0,
        dependency_strength="soft",
    ),
]


def build_service_definitions() -> dict[str, ServiceDefinition]:
    """Constructs ServiceDefinition models mapping each service to its registered dependencies."""
    definitions: dict[str, ServiceDefinition] = {}
    for name, config in SERVICE_CONFIGS.items():
        outgoing_deps = [dep for dep in SERVICE_TOPOLOGY if dep.from_service == name]
        definitions[name] = ServiceDefinition(
            name=name,
            description=config.description,
            owns_database=config.owns_database,
            dependencies=outgoing_deps,
        )
    return definitions
