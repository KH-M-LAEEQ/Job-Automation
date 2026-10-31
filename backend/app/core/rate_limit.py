"""Small in-process sliding-window limiter for authentication endpoints.

Limits are per backend process; behind several processes or hosts, put an equivalent
limit in the reverse proxy as well."""
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque:
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        return hits

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._trim(key, time.monotonic())) >= self.limit

    def hit(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._trim(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


# Failed logins are limited per (client address, account) and per client address. There is
# deliberately no per-account limit across all addresses: that would let anyone lock a
# victim out just by typing their email with wrong passwords.
login_failures_by_client_account = RateLimiter(limit=10, window_seconds=15 * 60)
login_failures_by_ip = RateLimiter(limit=50, window_seconds=15 * 60)
registrations_by_ip = RateLimiter(limit=10, window_seconds=60 * 60)
