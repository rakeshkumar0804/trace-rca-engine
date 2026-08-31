from datetime import datetime
from random import Random

from app.schemas.database_events import DatabaseEvent, DatabaseEventStatus
from .config import SERVICE_CONFIGS, ServiceConfig

DB_QUERIES: dict[str, list[str]] = {
    "checkout_db": [
        "SELECT * FROM cart WHERE user_id = ?",
        "INSERT INTO checkout_sessions (id, user_id, amount_cents, status) VALUES (?, ?, ?, ?)",
        "UPDATE checkout_sessions SET status = ?, updated_at = NOW() WHERE id = ?",
        "SELECT id, item_id, price_cents, quantity FROM cart_items WHERE cart_id = ?",
        "DELETE FROM cart_items WHERE cart_id = ? AND item_id = ?",
    ],
    "order_db": [
        "SELECT * FROM orders WHERE id = ?",
        "INSERT INTO orders (id, user_id, total_amount, status, created_at) VALUES (?, ?, ?, ?, NOW())",
        "INSERT INTO order_items (order_id, sku, quantity, unit_price) VALUES (?, ?, ?, ?)",
        "UPDATE orders SET status = ?, tracking_number = ? WHERE id = ?",
        "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
    ],
    "payment_db": [
        "SELECT * FROM customer_payment_methods WHERE customer_id = ? AND is_default = TRUE",
        "INSERT INTO payment_transactions (id, order_id, amount, currency, status) VALUES (?, ?, ?, ?, ?)",
        "UPDATE payment_transactions SET gateway_ref = ?, status = ?, completed_at = NOW() WHERE id = ?",
        "SELECT * FROM payment_transactions WHERE order_id = ?",
        "SELECT count(*), sum(amount) FROM payment_transactions WHERE created_at >= ? AND status = 'captured'",
    ],
}

DEFAULT_FALLBACK_QUERIES: list[str] = [
    "SELECT 1",
    "SELECT * FROM system_metadata WHERE key = ?",
    "UPDATE heartbeat SET last_seen = NOW() WHERE instance_id = ?",
]


def generate_healthy_database_events(
    service: str,
    window: list[datetime],
    rng: Random,
) -> list[DatabaseEvent]:
    """Generates realistic healthy database query and lock telemetry events for a DB-owning service."""
    config = SERVICE_CONFIGS.get(service)
    if not config or not config.owns_database:
        return []

    db_name = config.database_name or f"{service}_db"
    queries = DB_QUERIES.get(db_name, DEFAULT_FALLBACK_QUERIES)

    events: list[DatabaseEvent] = []

    for ts in window:
        # Sample 1-2 DB events per interval tick
        for _ in range(rng.randint(1, 2)):
            query = rng.choice(queries)
            is_slow = rng.random() < 0.02  # 2% slow queries in healthy state
            
            if is_slow:
                duration = rng.uniform(250.0, 650.0)
                status = DatabaseEventStatus.SLOW
            else:
                duration = rng.uniform(1.2, 28.0)
                status = DatabaseEventStatus.OK

            # Active connections stay safely within 15-40% of max
            active_conns = rng.randint(
                int(config.baseline_db_connections * 0.7),
                int(config.baseline_db_connections * 1.3),
            )
            # Normal healthy locking
            locks = rng.randint(0, 2)
            rows = rng.choice([1, 1, 1, rng.randint(2, 10)])

            event = DatabaseEvent(
                timestamp=ts,
                database=db_name,
                query_fingerprint=query,
                duration_ms=round(duration, 2),
                connections_active=active_conns,
                connections_max=config.max_db_connections,
                locks_held=locks,
                rows_affected=rows,
                status=status,
            )
            events.append(event)

    return events
