from datetime import datetime, timedelta
from random import Random
import uuid

from app.schemas.events import TraceSpan


def _gen_hex_id(rng: Random, length: int = 16) -> str:
    """Generates a random hex ID string of specific character length."""
    return f"{rng.getrandbits(length * 4):0{length}x}"


def generate_healthy_traces(
    window: list[datetime],
    rng: Random,
    sample_every_n: int = 3,
) -> list[TraceSpan]:
    """Generates realistic distributed trace trees across simulated microservices.
    
    Ensures root spans have parent_span_id=None and all child spans have valid parent references,
    with monotonically nested timing within the parent's execution window.
    """
    spans: list[TraceSpan] = []

    # Sample timestamps from the window so traces are distributed evenly
    sampled_timestamps = [ts for idx, ts in enumerate(window) if idx % sample_every_n == 0]

    for root_start in sampled_timestamps:
        trace_id = _gen_hex_id(rng, 32)
        flow_type = rng.choice(["checkout_flow", "order_lookup_flow", "cart_update_flow"])

        if flow_type == "checkout_flow":
            # 1. Root: api-gateway
            root_span_id = _gen_hex_id(rng, 16)
            auth_span_id = _gen_hex_id(rng, 16)
            checkout_span_id = _gen_hex_id(rng, 16)
            inv_span_id = _gen_hex_id(rng, 16)
            pay_span_id = _gen_hex_id(rng, 16)
            order_span_id = _gen_hex_id(rng, 16)
            notif_span_id = _gen_hex_id(rng, 16)

            # Child durations
            auth_dur = rng.uniform(4.0, 12.0)
            inv_dur = rng.uniform(8.0, 22.0)
            pay_dur = rng.uniform(50.0, 120.0)
            notif_dur = rng.uniform(10.0, 30.0)
            order_dur = notif_dur + rng.uniform(15.0, 35.0)
            checkout_dur = inv_dur + pay_dur + order_dur + rng.uniform(10.0, 25.0)
            root_dur = auth_dur + checkout_dur + rng.uniform(5.0, 15.0)

            # Timings
            t_auth_start = root_start + timedelta(milliseconds=rng.uniform(1.0, 3.0))
            t_chk_start = t_auth_start + timedelta(milliseconds=auth_dur + rng.uniform(1.0, 2.0))
            t_inv_start = t_chk_start + timedelta(milliseconds=rng.uniform(1.0, 3.0))
            t_pay_start = t_inv_start + timedelta(milliseconds=inv_dur + rng.uniform(1.0, 3.0))
            t_ord_start = t_pay_start + timedelta(milliseconds=pay_dur + rng.uniform(1.0, 3.0))
            t_notif_start = t_ord_start + timedelta(milliseconds=rng.uniform(2.0, 5.0))

            # Status
            status = "ok" if rng.random() > 0.002 else "error"

            spans.extend([
                TraceSpan(
                    trace_id=trace_id,
                    span_id=root_span_id,
                    parent_span_id=None,
                    service="api-gateway",
                    operation="POST /api/v1/checkout",
                    start_time=root_start,
                    duration_ms=round(root_dur, 2),
                    status=status,
                    attributes={"http.method": "POST", "http.status_code": "200" if status == "ok" else "500"},
                ),
                TraceSpan(
                    trace_id=trace_id,
                    span_id=auth_span_id,
                    parent_span_id=root_span_id,
                    service="auth-service",
                    operation="POST /auth/validate",
                    start_time=t_auth_start,
                    duration_ms=round(auth_dur, 2),
                    status="ok",
                    attributes={"rpc.system": "grpc", "rpc.service": "AuthService"},
                ),
                TraceSpan(
                    trace_id=trace_id,
                    span_id=checkout_span_id,
                    parent_span_id=root_span_id,
                    service="checkout-service",
                    operation="POST /checkout/process",
                    start_time=t_chk_start,
                    duration_ms=round(checkout_dur, 2),
                    status=status,
                    attributes={"http.route": "/checkout/process", "user.tier": "standard"},
                ),
                TraceSpan(
                    trace_id=trace_id,
                    span_id=inv_span_id,
                    parent_span_id=checkout_span_id,
                    service="inventory-service",
                    operation="POST /inventory/reserve",
                    start_time=t_inv_start,
                    duration_ms=round(inv_dur, 2),
                    status="ok",
                    attributes={"rpc.method": "ReserveStock"},
                ),
                TraceSpan(
                    trace_id=trace_id,
                    span_id=pay_span_id,
                    parent_span_id=checkout_span_id,
                    service="payment-service",
                    operation="POST /payments/charge",
                    start_time=t_pay_start,
                    duration_ms=round(pay_dur, 2),
                    status="ok",
                    attributes={"payment.gateway": "stripe", "currency": "USD"},
                ),
                TraceSpan(
                    trace_id=trace_id,
                    span_id=order_span_id,
                    parent_span_id=checkout_span_id,
                    service="order-service",
                    operation="POST /orders/create",
                    start_time=t_ord_start,
                    duration_ms=round(order_dur, 2),
                    status="ok",
                    attributes={"rpc.method": "CreateOrder"},
                ),
                TraceSpan(
                    trace_id=trace_id,
                    span_id=notif_span_id,
                    parent_span_id=order_span_id,
                    service="notification-service",
                    operation="POST /notifications/send",
                    start_time=t_notif_start,
                    duration_ms=round(notif_dur, 2),
                    status="ok",
                    attributes={"notification.channel": "email"},
                ),
            ])

        elif flow_type == "order_lookup_flow":
            root_span_id = _gen_hex_id(rng, 16)
            auth_span_id = _gen_hex_id(rng, 16)
            order_span_id = _gen_hex_id(rng, 16)

            auth_dur = rng.uniform(3.0, 9.0)
            order_dur = rng.uniform(15.0, 45.0)
            root_dur = auth_dur + order_dur + rng.uniform(4.0, 10.0)

            t_auth_start = root_start + timedelta(milliseconds=rng.uniform(1.0, 2.0))
            t_ord_start = t_auth_start + timedelta(milliseconds=auth_dur + rng.uniform(1.0, 2.0))

            spans.extend([
                TraceSpan(
                    trace_id=trace_id,
                    span_id=root_span_id,
                    parent_span_id=None,
                    service="api-gateway",
                    operation="GET /api/v1/orders/10293",
                    start_time=root_start,
                    duration_ms=round(root_dur, 2),
                    status="ok",
                    attributes={"http.method": "GET", "http.status_code": "200"},
                ),
                TraceSpan(
                    trace_id=trace_id,
                    span_id=auth_span_id,
                    parent_span_id=root_span_id,
                    service="auth-service",
                    operation="POST /auth/validate",
                    start_time=t_auth_start,
                    duration_ms=round(auth_dur, 2),
                    status="ok",
                    attributes={"rpc.system": "grpc"},
                ),
                TraceSpan(
                    trace_id=trace_id,
                    span_id=order_span_id,
                    parent_span_id=root_span_id,
                    service="order-service",
                    operation="GET /orders/10293",
                    start_time=t_ord_start,
                    duration_ms=round(order_dur, 2),
                    status="ok",
                    attributes={"db.query": "SELECT * FROM orders WHERE id = 10293"},
                ),
            ])

        else:  # cart_update_flow
            root_span_id = _gen_hex_id(rng, 16)
            auth_span_id = _gen_hex_id(rng, 16)
            chk_span_id = _gen_hex_id(rng, 16)
            inv_span_id = _gen_hex_id(rng, 16)

            auth_dur = rng.uniform(3.0, 8.0)
            inv_dur = rng.uniform(6.0, 18.0)
            chk_dur = inv_dur + rng.uniform(10.0, 25.0)
            root_dur = auth_dur + chk_dur + rng.uniform(3.0, 8.0)

            t_auth_start = root_start + timedelta(milliseconds=rng.uniform(1.0, 2.0))
            t_chk_start = t_auth_start + timedelta(milliseconds=auth_dur + rng.uniform(1.0, 2.0))
            t_inv_start = t_chk_start + timedelta(milliseconds=rng.uniform(1.0, 3.0))

            spans.extend([
                TraceSpan(
                    trace_id=trace_id,
                    span_id=root_span_id,
                    parent_span_id=None,
                    service="api-gateway",
                    operation="PUT /api/v1/cart/items",
                    start_time=root_start,
                    duration_ms=round(root_dur, 2),
                    status="ok",
                    attributes={"http.method": "PUT", "http.status_code": "200"},
                ),
                TraceSpan(
                    trace_id=trace_id,
                    span_id=auth_span_id,
                    parent_span_id=root_span_id,
                    service="auth-service",
                    operation="POST /auth/validate",
                    start_time=t_auth_start,
                    duration_ms=round(auth_dur, 2),
                    status="ok",
                    attributes={"rpc.system": "grpc"},
                ),
                TraceSpan(
                    trace_id=trace_id,
                    span_id=chk_span_id,
                    parent_span_id=root_span_id,
                    service="checkout-service",
                    operation="PUT /cart/items",
                    start_time=t_chk_start,
                    duration_ms=round(chk_dur, 2),
                    status="ok",
                    attributes={"cart.action": "add_item"},
                ),
                TraceSpan(
                    trace_id=trace_id,
                    span_id=inv_span_id,
                    parent_span_id=chk_span_id,
                    service="inventory-service",
                    operation="GET /inventory/check",
                    start_time=t_inv_start,
                    duration_ms=round(inv_dur, 2),
                    status="ok",
                    attributes={"sku": "SKU-9921"},
                ),
            ])

    return spans
