"""In-memory sliding window rate limiter for expensive demo and investigation endpoints.

Hardened for reverse proxy deployment (e.g. Render / Cloudflare) with configurable proxy header trust
and bounded memory retention.
"""

import ipaddress
import logging
import os
import time
from collections import defaultdict
from typing import Callable, Iterable
from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("trace.api.rate_limiter")

# Default trusted proxy CIDRs (private, loopback, and carrier-grade NAT)
DEFAULT_TRUSTED_PROXIES = [
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "100.64.0.0/10",
    "fc00::/7",
    "fe80::/10",
]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Protects incident generation and LLM investigation execution endpoints against abuse.
    
    Proxy Trust Configuration:
      - Set environment variable `TRUST_PROXY_HEADERS=true` when running behind a verified reverse
        proxy (e.g. Render, AWS ALB, Cloudflare).
      - When `TRUST_PROXY_HEADERS` is true, the middleware validates that the direct connection
        (`request.client.host`) originates from a known/trusted proxy CIDR (`TRUSTED_PROXIES`).
      - It traverses `X-Forwarded-For` from right to left, stripping trusted intermediate proxies
        and picking the first untrusted IP (the genuine client IP). This prevents attackers from
        forging the forwarding chain.
      - If direct socket host is not in trusted proxies, client-supplied proxy headers are ignored.
      - When `TRUST_PROXY_HEADERS` is false (default), client headers are strictly ignored and
        `request.client.host` is used directly.
    
    Memory Bounding:
      - Automatically purges expired IP history when tracked IP count exceeds `max_tracked_ips`.
    """

    _instances: list["RateLimitMiddleware"] = []

    def __init__(
        self,
        app,
        max_requests_per_minute: int = 15,
        trust_proxy_headers: bool | None = None,
        trusted_proxies: Iterable[str] | None = None,
        max_tracked_ips: int = 2000,
        restricted_prefixes: tuple[str, ...] = (
            "/api/incidents/generate",
            "/api/investigations/run",
            "/api/investigations/demo",
        ),
    ):
        super().__init__(app)
        RateLimitMiddleware._instances.append(self)
        self.max_requests = max_requests_per_minute
        self.restricted_prefixes = restricted_prefixes
        self.max_tracked_ips = max_tracked_ips
        
        if trust_proxy_headers is not None:
            self.trust_proxy_headers = trust_proxy_headers
        else:
            self.trust_proxy_headers = os.getenv("TRUST_PROXY_HEADERS", "false").lower() in ("true", "1", "yes")

        # Configure trusted proxy networks
        configured_proxies = os.getenv("TRUSTED_PROXIES", "")
        if trusted_proxies is not None:
            proxy_list = list(trusted_proxies)
        elif configured_proxies.strip():
            proxy_list = [p.strip() for p in configured_proxies.split(",") if p.strip()]
        else:
            proxy_list = DEFAULT_TRUSTED_PROXIES

        self._trusted_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for p in proxy_list:
            try:
                self._trusted_networks.append(ipaddress.ip_network(p, strict=False))
            except ValueError:
                logger.warning(f"Invalid trusted proxy CIDR or IP configured: {p}")

        self._history: dict[str, list[float]] = defaultdict(list)

    @classmethod
    def reset_all_instances(cls) -> None:
        """Helper for test suites to clear all rate limit histories."""
        for inst in cls._instances:
            inst._history.clear()

    def _is_ip_trusted(self, ip_str: str) -> bool:
        """Checks if an IP string belongs to any configured trusted proxy network."""
        try:
            ip_obj = ipaddress.ip_address(ip_str.strip())
            return any(ip_obj in net for net in self._trusted_networks)
        except ValueError:
            return False

    def _extract_client_ip(self, request: Request) -> str:
        """Extracts client IP securely according to proxy trust policy.
        
        Traverses X-Forwarded-For from right to left to prevent spoofed header bypass.
        """
        direct_ip = request.client.host if request.client else "127.0.0.1"

        if not self.trust_proxy_headers:
            return direct_ip

        # Only trust proxy headers if direct socket connection originates from a trusted proxy
        if not self._is_ip_trusted(direct_ip):
            return direct_ip

        # Check platform-specific direct headers from trusted proxies first
        for platform_hdr in ("cf-connecting-ip", "x-render-client-ip", "true-client-ip"):
            plat_ip = request.headers.get(platform_hdr)
            if plat_ip:
                clean_ip = plat_ip.strip()
                try:
                    ipaddress.ip_address(clean_ip)
                    return clean_ip
                except ValueError:
                    pass

        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ips = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
            # Traverse from right to left; return first IP that is not a trusted proxy
            for ip in reversed(ips):
                try:
                    ip_obj = ipaddress.ip_address(ip)
                    if not self._is_ip_trusted(ip):
                        return ip
                except ValueError:
                    continue
            if ips:
                return ips[0]

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            clean_real = real_ip.strip()
            try:
                ipaddress.ip_address(clean_real)
                return clean_real
            except ValueError:
                pass

        return direct_ip

    def _cleanup_expired(self, now: float, cutoff: float) -> None:
        """Purges expired IP history to enforce bounded memory retention."""
        if len(self._history) <= self.max_tracked_ips:
            return

        expired_ips = [
            ip for ip, timestamps in self._history.items()
            if not timestamps or timestamps[-1] <= cutoff
        ]
        for ip in expired_ips:
            self._history.pop(ip, None)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check if request path matches rate-limited endpoints
        path = request.url.path
        is_restricted = any(path.startswith(prefix) for prefix in self.restricted_prefixes)

        if is_restricted and request.method == "POST":
            client_ip = self._extract_client_ip(request)
            now = time.time()
            cutoff = now - 60.0

            # Prune timestamps older than 60 seconds
            history = [t for t in self._history[client_ip] if t > cutoff]

            if len(history) >= self.max_requests:
                oldest = history[0]
                retry_after = max(1, int(60.0 - (now - oldest)))
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": f"Rate limit exceeded. Please wait {retry_after}s before starting a new investigation."},
                    headers={"Retry-After": str(retry_after)},
                )

            history.append(now)
            self._history[client_ip] = history

            # Opportunistic memory bounds enforcement
            self._cleanup_expired(now, cutoff)

        return await call_next(request)
