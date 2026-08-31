"""In-memory sliding window rate limiter for expensive demo and investigation endpoints."""

import time
from collections import defaultdict
from typing import Callable
from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Protects incident generation and LLM investigation execution endpoints against abuse."""

    def __init__(
        self,
        app,
        max_requests_per_minute: int = 15,
        restricted_prefixes: tuple[str, ...] = (
            "/api/incidents/generate",
            "/api/investigations/run",
            "/api/investigations/demo",
        ),
    ):
        super().__init__(app)
        self.max_requests = max_requests_per_minute
        self.restricted_prefixes = restricted_prefixes
        self._history: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check if request path matches rate-limited endpoints
        path = request.url.path
        is_restricted = any(path.startswith(prefix) for prefix in self.restricted_prefixes)

        if is_restricted and request.method == "POST":
            # Extract client IP
            client_ip = request.client.host if request.client else "unknown"
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                client_ip = forwarded.split(",")[0].strip()

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

        return await call_next(request)
