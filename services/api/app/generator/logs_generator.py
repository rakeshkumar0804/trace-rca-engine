from datetime import datetime
from random import Random
import uuid

from app.schemas.events import EventSeverity, LogEntry
from .config import SERVICE_CONFIGS, ServiceConfig


# Realistic message templates per service and severity
LOG_TEMPLATES: dict[str, dict[EventSeverity, list[str]]] = {
    "api-gateway": {
        EventSeverity.INFO: [
            "Inbound request method={method} path={path} remote_addr=10.0.{ip3}.{ip4} client_id={client_id}",
            "Routed request path={path} target_service={target} duration_ms={duration_ms} status=200",
            "SSL handshake completed cipher=TLS_AES_256_GCM_SHA384 client_ip=10.0.{ip3}.{ip4}",
            "CORS preflight request handled origin=https://app.corp.internal status=204",
        ],
        EventSeverity.WARNING: [
            "Upstream response time elevated target={target} duration_ms={duration_ms} threshold=200ms",
            "Rate limit bucket 80% capacity reached for client_id={client_id}",
            "Client closed connection before response completed path={path}",
        ],
        EventSeverity.ERROR: [
            "Upstream service connection reset target={target} path={path}",
            "HTTP 502 bad gateway from downstream host={target}",
            "Request timeout exceeded 5000ms path={path} client_id={client_id}",
        ],
    },
    "auth-service": {
        EventSeverity.INFO: [
            "JWT token validated successfully user_id={user_id} scope=read:checkout expiry_ttl=3420s",
            "Session refreshed for subject={user_id} session_id={session_id}",
            "Public key cache updated from JWKS provider key_id=k-{key_id}",
            "API key authentication succeeded service_principal={client_id}",
        ],
        EventSeverity.WARNING: [
            "Expired refresh token presented user_id={user_id} rejecting token_rotation",
            "Suspicious login pattern detected user_id={user_id} geo_ip=198.51.100.{ip4}",
        ],
        EventSeverity.ERROR: [
            "Signature validation failure token_id={session_id} invalid_key_id",
            "Redis session cache connection timeout host=session-redis:6379",
        ],
    },
    "checkout-service": {
        EventSeverity.INFO: [
            "Checkout session initialized checkout_id={checkout_id} user_id={user_id} cart_items={qty}",
            "Inventory reservation confirmed order_id={order_id} reservation_id=res-{res_id}",
            "Payment charge authorized checkout_id={checkout_id} amount_cents={amount}",
            "Cart state persisted to checkout_db session_id={checkout_id}",
        ],
        EventSeverity.WARNING: [
            "Payment confirmation retry attempt 1 for checkout_id={checkout_id}",
            "Slow database query on checkout_sessions duration_ms={duration_ms}",
            "Item stock low during reservation item_id=item-{item_id} remaining=3",
        ],
        EventSeverity.ERROR: [
            "Payment authorization rejected by upstream gateway error_code=insufficient_funds",
            "Checkout transaction rolled back checkout_id={checkout_id} error=order_creation_failed",
            "Database lock wait timeout acquiring lock on checkout_sessions",
        ],
    },
    "order-service": {
        EventSeverity.INFO: [
            "Order created successfully order_id={order_id} user_id={user_id} total_usd={amount_usd}",
            "Order state machine transitioned order_id={order_id} from=PENDING to=PROCESSING",
            "Dispatched order event to notification service order_id={order_id}",
            "Order items batch inserted count={qty} duration_ms={duration_ms}",
        ],
        EventSeverity.WARNING: [
            "Order status notification message delayed in queue order_id={order_id} lag_ms=450",
            "Duplicate idempotent order request received order_id={order_id} returning existing",
        ],
        EventSeverity.ERROR: [
            "Order persistence failed foreign_key_violation user_id={user_id}",
            "Deadlock detected during concurrent order update order_id={order_id}",
        ],
    },
    "payment-service": {
        EventSeverity.INFO: [
            "Payment intent created intent_id=pi_{res_id} amount_cents={amount} currency=USD",
            "Charge capture succeeded charge_id=ch_{res_id} gateway=stripe response_time_ms={duration_ms}",
            "Webhook received from payment provider event_type=charge.succeeded id=evt_{res_id}",
            "Payment audit record written to payment_db tx_id=tx-{key_id}",
        ],
        EventSeverity.WARNING: [
            "Card network latency high for payment provider latency_ms={duration_ms}",
            "Stripe API idempotency key replay detected intent_id=pi_{res_id}",
        ],
        EventSeverity.ERROR: [
            "Payment provider gateway timeout error_code=gateway_timeout intent_id=pi_{res_id}",
            "Database connection pool unavailable executing payment_audit_insert",
        ],
    },
    "inventory-service": {
        EventSeverity.INFO: [
            "Stock availability verified item_id=sku-{item_id} available_qty=142",
            "Item reservation locked item_id=sku-{item_id} qty={qty} ttl_sec=900",
            "Inventory replenishment sync completed items_synced=500 duration_ms={duration_ms}",
        ],
        EventSeverity.WARNING: [
            "Inventory cache miss key=sku-{item_id} fetching from master data store",
            "Reservation expiring soon reservation_id=res-{res_id} item_id=sku-{item_id}",
        ],
        EventSeverity.ERROR: [
            "Reservation lock acquisition failed lock_contention item_id=sku-{item_id}",
            "Inventory cache node connection refused host=inv-cache:6379",
        ],
    },
    "notification-service": {
        EventSeverity.INFO: [
            "Notification job queued template=order_confirmation recipient_id={user_id}",
            "Email dispatched via SendGrid recipient={user_id}@example.com message_id=msg-{res_id}",
            "SMS notification delivered carrier=Twilio status=delivered sid=SM{res_id}",
        ],
        EventSeverity.WARNING: [
            "SendGrid API response time degraded duration_ms={duration_ms}",
            "Email recipient bounced status=suppressed recipient={user_id}@example.com",
        ],
        EventSeverity.ERROR: [
            "Failed to send email notification SendGrid HTTP 500 error",
            "SMS delivery failed carrier rejected destination_number",
        ],
    },
}

DEFAULT_FALLBACK_TEMPLATES: dict[EventSeverity, list[str]] = {
    EventSeverity.INFO: ["Service health heartbeat status=OK memory_mb={amount} active_threads=8"],
    EventSeverity.WARNING: ["Elevated garbage collection pause duration_ms={duration_ms}"],
    EventSeverity.ERROR: ["Unhandled exception in request processing pipeline"],
}


def _format_message(template: str, rng: Random) -> str:
    """Populates template variables with realistic pseudo-random values."""
    vars_dict = {
        "method": rng.choice(["GET", "POST", "PUT"]),
        "path": rng.choice(["/api/v1/checkout", "/api/v1/orders", "/api/v1/auth/token", "/healthz"]),
        "ip3": str(rng.randint(1, 254)),
        "ip4": str(rng.randint(1, 254)),
        "client_id": f"cli-{rng.randint(1000, 9999)}",
        "target": rng.choice(["checkout-service", "auth-service", "order-service", "payment-service"]),
        "duration_ms": f"{rng.uniform(5.0, 180.0):.1f}",
        "user_id": f"usr-{rng.randint(10000, 99999)}",
        "session_id": uuid.UUID(int=rng.getrandbits(128)).hex[:16],
        "key_id": f"{rng.randint(100, 999)}",
        "checkout_id": f"chk-{uuid.UUID(int=rng.getrandbits(128)).hex[:10]}",
        "order_id": f"ord-{rng.randint(100000, 999999)}",
        "qty": str(rng.randint(1, 5)),
        "res_id": uuid.UUID(int=rng.getrandbits(128)).hex[:8],
        "amount": str(rng.randint(1500, 25000)),
        "amount_usd": f"{rng.uniform(15.0, 250.0):.2f}",
        "item_id": f"{rng.randint(1000, 9999)}",
    }
    return template.format(**vars_dict)


def generate_healthy_logs(
    service: str,
    window: list[datetime],
    rng: Random,
) -> list[LogEntry]:
    """Generates a realistic stream of healthy operational log entries for a given service.
    
    Severity distribution follows the service's baseline error rate (~0.1-0.3% ERROR, ~2.5% WARNING, rest INFO).
    """
    config = SERVICE_CONFIGS.get(service, ServiceConfig(name=service, description="Service", owns_database=False))
    service_templates = LOG_TEMPLATES.get(service, DEFAULT_FALLBACK_TEMPLATES)
    
    logs: list[LogEntry] = []
    
    for ts in window:
        # Determine number of log lines for this timestamp tick (1-3 logs per tick)
        num_logs = rng.randint(1, 3)
        for _ in range(num_logs):
            roll = rng.random()
            if roll < config.baseline_error_rate:
                severity = EventSeverity.ERROR
            elif roll < config.baseline_error_rate + 0.025:
                severity = EventSeverity.WARNING
            else:
                severity = EventSeverity.INFO
                
            templates = service_templates.get(severity, DEFAULT_FALLBACK_TEMPLATES.get(severity, ["Log event"]))
            template = rng.choice(templates)
            message = _format_message(template, rng)
            
            trace_hex = uuid.UUID(int=rng.getrandbits(128)).hex
            req_hex = uuid.UUID(int=rng.getrandbits(128)).hex[:12]
            
            log = LogEntry(
                timestamp=ts,
                service=service,
                severity=severity,
                message=message,
                trace_id=trace_hex,
                request_id=f"req-{req_hex}",
                metadata={
                    "env": "production",
                    "host": f"{service}-pod-{rng.randint(1, 4)}",
                },
            )
            logs.append(log)
            
    return logs
