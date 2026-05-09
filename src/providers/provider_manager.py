"""
Provider Manager — Production-grade multi-provider state machine.

Tracks health, latency, rate limits, and failures for each inference provider.
Selects the best available provider with automatic failover.
"""

import time
import threading
from enum import Enum
from dataclasses import dataclass, field
from src.logger import logging


class ProviderStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    DOWN = "down"


@dataclass
class ProviderState:
    """Tracks the real-time health of a single provider."""
    name: str
    status: ProviderStatus = ProviderStatus.HEALTHY
    consecutive_failures: int = 0
    total_requests: int = 0
    total_failures: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    avg_latency_ms: float = 0.0
    rate_limit_reset_at: float = 0.0
    _latency_window: list = field(default_factory=list)

    # Thresholds
    MAX_CONSECUTIVE_FAILURES: int = 3
    DEGRADED_LATENCY_MS: float = 5000.0  # 5 seconds
    LATENCY_WINDOW_SIZE: int = 10

    def record_success(self, latency_ms: float):
        """Record a successful request and update metrics."""
        self.consecutive_failures = 0
        self.total_requests += 1
        self.last_success_time = time.time()

        # Rolling latency window
        self._latency_window.append(latency_ms)
        if len(self._latency_window) > self.LATENCY_WINDOW_SIZE:
            self._latency_window.pop(0)
        self.avg_latency_ms = sum(self._latency_window) / len(self._latency_window)

        # Recover from degraded if latency improves
        if self.status == ProviderStatus.DEGRADED and self.avg_latency_ms < self.DEGRADED_LATENCY_MS:
            self.status = ProviderStatus.HEALTHY
            logging.info(f"✅ [{self.name}] Recovered from DEGRADED → HEALTHY (avg latency: {self.avg_latency_ms:.0f}ms)")

        if self.status in (ProviderStatus.RATE_LIMITED, ProviderStatus.DOWN):
            self.status = ProviderStatus.HEALTHY
            logging.info(f"✅ [{self.name}] Recovered → HEALTHY")

    def record_failure(self, error_type: str = "unknown"):
        """Record a failed request and potentially downgrade status."""
        self.consecutive_failures += 1
        self.total_failures += 1
        self.total_requests += 1
        self.last_failure_time = time.time()

        if self.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            self.status = ProviderStatus.DOWN
            logging.warning(f"🔴 [{self.name}] Marked DOWN after {self.consecutive_failures} consecutive failures ({error_type})")
        elif self.status == ProviderStatus.HEALTHY:
            self.status = ProviderStatus.DEGRADED
            logging.warning(f"🟡 [{self.name}] Marked DEGRADED ({error_type})")

    def mark_rate_limited(self, reset_after_seconds: float = 60.0):
        """Mark provider as rate-limited with a reset time."""
        self.status = ProviderStatus.RATE_LIMITED
        self.rate_limit_reset_at = time.time() + reset_after_seconds
        logging.warning(f"⚠️ [{self.name}] RATE LIMITED — will retry after {reset_after_seconds:.0f}s")

    def is_available(self) -> bool:
        """Check if this provider can accept requests right now."""
        if self.status == ProviderStatus.HEALTHY:
            return True
        if self.status == ProviderStatus.DEGRADED:
            return True  # Still usable, just slower
        if self.status == ProviderStatus.RATE_LIMITED:
            # Check if rate limit window has passed
            if time.time() > self.rate_limit_reset_at:
                self.status = ProviderStatus.HEALTHY
                logging.info(f"🔄 [{self.name}] Rate limit window expired → HEALTHY")
                return True
            return False
        return False  # DOWN


class ProviderManager:
    """
    Manages multiple inference providers with automatic failover.
    Thread-safe for use with Uvicorn workers.
    """

    def __init__(self, name: str = "default"):
        self._lock = threading.Lock()
        self.name = name
        
        # ASR uses Groq -> Local Whisper. Generation/Chat use Groq -> HF -> Ollama.
        # We handle the specific provider names differently if it's the ASR manager.
        if name == "ASR":
            self.providers = {
                "groq": ProviderState(name=f"Groq-{name}"),
                "local_whisper": ProviderState(name=f"LocalWhisper-{name}"),
            }
            self.priority_order = ["groq", "local_whisper"]
        else:
            self.providers = {
                "groq": ProviderState(name=f"Groq-{name}"),
                "huggingface": ProviderState(name=f"HuggingFace-{name}"),
                "ollama": ProviderState(name=f"Ollama-{name}"),
            }
            self.priority_order = ["groq", "huggingface", "ollama"]
            
        logging.info(f"🧠 Provider Manager [{name}] initialized")

    def select_provider(self) -> str:
        """
        Select the best available provider based on priority and health.
        Returns provider name string.
        """
        with self._lock:
            for name in self.priority_order:
                state = self.providers[name]
                if state.is_available():
                    return name

            # All cloud providers down — force fallback
            if self.name == "ASR":
                logging.warning("⚠️ All cloud ASR providers unavailable — forcing Local Whisper fallback")
                self.providers["local_whisper"].status = ProviderStatus.HEALTHY
                return "local_whisper"
            else:
                logging.warning("⚠️ All cloud LLM providers unavailable — forcing Ollama fallback")
                self.providers["ollama"].status = ProviderStatus.HEALTHY
                return "ollama"

    def record_success(self, provider_name: str, latency_ms: float):
        """Record a successful request for the given provider."""
        with self._lock:
            if provider_name in self.providers:
                self.providers[provider_name].record_success(latency_ms)

    def record_failure(self, provider_name: str, error_type: str = "unknown"):
        """Record a failed request for the given provider."""
        with self._lock:
            if provider_name in self.providers:
                self.providers[provider_name].record_failure(error_type)

    def mark_rate_limited(self, provider_name: str, reset_after: float = 60.0):
        """Mark a provider as rate-limited."""
        with self._lock:
            if provider_name in self.providers:
                self.providers[provider_name].mark_rate_limited(reset_after)

    def get_status_report(self) -> dict:
        """Get a snapshot of all provider statuses for monitoring."""
        with self._lock:
            return {
                name: {
                    "status": state.status.value,
                    "avg_latency_ms": round(state.avg_latency_ms, 1),
                    "consecutive_failures": state.consecutive_failures,
                    "total_requests": state.total_requests,
                }
                for name, state in self.providers.items()
            }

    def force_recover(self, provider_name: str):
        """Manually force a provider back to healthy (used by health monitor)."""
        with self._lock:
            if provider_name in self.providers:
                self.providers[provider_name].status = ProviderStatus.HEALTHY
                self.providers[provider_name].consecutive_failures = 0
                logging.info(f"💚 [{provider_name}] Force-recovered to HEALTHY by health monitor")


# Global singleton instance
provider_manager = ProviderManager(name="ASR")
