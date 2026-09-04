"""Thread-safe In-Memory TTL Cache and SingleFlight (Request Coalescing) Utilities.

Designed to prevent Thundering Herd Problems and Cascading Fallback Failures
when communicating with external search services (e.g. 2MD, Investing.com, RSS).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class TTLCache:
    """Thread-safe In-Memory Cache with per-key Time-To-Live (TTL) and LRU/FIFO eviction.
    
    Supports 'get_stale' for graceful degradation (Stale-While-Revalidate pattern)
    when external upstreams suffer temporary downtime or timeouts.
    """

    def __init__(self, default_ttl: float = 300.0, max_size: int = 500):
        self.default_ttl = float(default_ttl)
        self.max_size = int(max_size)
        # key -> (expire_at, set_at, data)
        self._cache: Dict[str, Tuple[float, float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """Retrieve value if key exists and has not expired."""
        now = time.time()
        with self._lock:
            if key in self._cache:
                expire_at, _, data = self._cache[key]
                if now < expire_at:
                    return data
        return None

    def get_stale(self, key: str) -> Optional[Any]:
        """Retrieve value even if expired (used for disaster recovery / fallback)."""
        with self._lock:
            if key in self._cache:
                _, _, data = self._cache[key]
                return data
        return None

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Store value with specified TTL (in seconds) or default TTL."""
        now = time.time()
        effective_ttl = float(ttl) if ttl is not None else self.default_ttl
        with self._lock:
            if len(self._cache) >= self.max_size:
                # Evict expired keys first
                for k, (exp, _, _) in list(self._cache.items()):
                    if now >= exp:
                        del self._cache[k]

                # If still at or over max_size, evict oldest entry
                if len(self._cache) >= self.max_size:
                    oldest_key = None
                    oldest_time = float("inf")
                    for k, (_, st, _) in self._cache.items():
                        if st < oldest_time:
                            oldest_time = st
                            oldest_key = k
                    if oldest_key:
                        del self._cache[oldest_key]

            self._cache[key] = (now + effective_ttl, now, value)

    def contains(self, key: str) -> bool:
        """Check if an unexpired key exists."""
        return self.get(key) is not None

    def clear(self) -> None:
        """Clear all entries."""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """Get current number of entries."""
        with self._lock:
            return len(self._cache)


class _Call:
    """Internal container for an in-flight singleflight call."""

    def __init__(self):
        self.event = threading.Event()
        self.result: Any = None
        self.exception: Optional[Exception] = None


class SingleFlight:
    """Request coalescing group (equivalent to Go's singleflight.Group).
    
    Ensures that for any given key, only one execution of fn(*args, **kwargs)
    is in flight at any given time. Concurrent callers with the same key will block
    and share the exact same returned value or raised exception.
    """

    def __init__(self):
        self._calls: Dict[str, _Call] = {}
        self._lock = threading.Lock()

    def run(self, key: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute fn if no other call with key is in flight, otherwise wait and share result."""
        with self._lock:
            if key in self._calls:
                call = self._calls[key]
                is_leader = False
            else:
                call = _Call()
                self._calls[key] = call
                is_leader = True

        if not is_leader:
            # Wait for leader to complete (max wait 30s to prevent hang)
            completed = call.event.wait(timeout=30.0)
            if not completed:
                logger.warning("SingleFlight follower timed out waiting for key: %s", key)
                # Fallback to independent execution if leader hung
                return fn(*args, **kwargs)

            if call.exception is not None:
                raise call.exception
            return call.result

        try:
            res = fn(*args, **kwargs)
            call.result = res
            return res
        except Exception as exc:
            call.exception = exc
            raise exc
        finally:
            call.event.set()
            with self._lock:
                self._calls.pop(key, None)
