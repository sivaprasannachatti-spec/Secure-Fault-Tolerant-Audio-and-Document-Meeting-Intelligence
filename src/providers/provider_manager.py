"""
Provider Manager — Production-grade multi-provider state machine.

Tracks health, latency, rate limits, and failures for each inference provider.
Selects the best available provider with automatic failover.
"""

import os
import platform
# Python 3.14 Windows Hang Fix
if os.name == 'nt' and not hasattr(platform, '_monkeypatched'):
    platform.system = lambda: "Windows"
    platform.release = lambda: "10"
    platform.version = lambda: "10.0.19041"
    platform.python_version = lambda: "3.14.3"
    platform._monkeypatched = True

import os
import time
import threading
from enum import Enum
from dataclasses import dataclass, field
from src.logger import logging

# ============================================================================
# Enums & State Objects
# ============================================================================

class KeyStatus(Enum):
    ACTIVE = "active"
    RATE_LIMITED = "rate_limited"
    COOLDOWN = "cooldown"
    FAILED = "failed"

class ProviderStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    DOWN = "down"

@dataclass
class KeyState:
    """Tracks individual API key health and quotas."""
    key: str
    status: KeyStatus = KeyStatus.ACTIVE
    last_used: float = 0.0
    cooldown_until: float = 0.0
    failure_count: int = 0
    total_calls: int = 0

# ============================================================================
# Key Rotator (The "Key Pool" Orchestrator)
# ============================================================================

class KeyRotator:
    """Enterprise-grade Multi-Key Orchestrator with Round-Robin and Recovery."""
    def __init__(self, env_var_name: str, cooldown_seconds: int = 60):
        self.env_var_name = env_var_name
        self.cooldown_seconds = cooldown_seconds
        
        raw = os.getenv(env_var_name, "")
        if not raw:
            raw = os.getenv(env_var_name.replace("_KEYS", "_KEY"), "")
        if not raw and "ASSEMBLY" in env_var_name:
            raw = os.getenv("ASSEMBLY_API_KEY", "") or os.getenv("ASSEMBLY_API_KEYS", "")
            
        # Always split by comma to support lists in singular or plural env vars
        keys = [k.strip() for k in raw.split(",") if k.strip()]

        self.key_states = [KeyState(key=k) for k in keys]
        self.current_ptr = 0
        self.lock = threading.Lock()
        
        if keys:
            logging.info(f"🔑 [{env_var_name}] Initialized with {len(keys)} keys.")

    def get_key(self) -> str:
        """Selects the next available key using Round-Robin logic."""
        with self.lock:
            if not self.key_states:
                return None
            
            now = time.time()
            
            # 1. Recover keys from cooldown
            for state in self.key_states:
                if state.status in (KeyStatus.RATE_LIMITED, KeyStatus.COOLDOWN):
                    if now >= state.cooldown_until:
                        state.status = KeyStatus.ACTIVE
                        logging.info(f"♻️ Key Recovery: Key index {self.key_states.index(state)} for {self.env_var_name} is back online.")

            # 2. Find next ACTIVE key starting from current_ptr (Round Robin)
            for i in range(len(self.key_states)):
                idx = (self.current_ptr + i) % len(self.key_states)
                state = self.key_states[idx]
                if state.status == KeyStatus.ACTIVE:
                    self.current_ptr = (idx + 1) % len(self.key_states)
                    state.last_used = now
                    state.total_calls += 1
                    return state.key
            
            return None # All keys currently limited/down

    def mark_limited(self, key: str):
        """Sidelining a specific key without killing the whole provider."""
        with self.lock:
            for state in self.key_states:
                if state.key == key:
                    state.status = KeyStatus.RATE_LIMITED
                    state.cooldown_until = time.time() + self.cooldown_seconds
                    logging.warning(f"⏳ Key Sidelined: Index {self.key_states.index(state)} for {self.env_var_name} hit rate limit. Cooldown: {self.cooldown_seconds}s")
                    break

    def has_active_keys(self) -> bool:
        """Check if at least one key is available."""
        with self.lock:
            now = time.time()
            # A provider is available if it has an active key OR a key whose cooldown is about to expire
            return any(s.status == KeyStatus.ACTIVE or now >= s.cooldown_until for s in self.key_states)


# ============================================================================
# Provider State (The "Service" Orchestrator)
# ============================================================================

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
    key_rotator: KeyRotator = None

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

    def mark_rate_limited(self, key_if_any: str = None, reset_after_seconds: float = 60.0):
        """Mark provider as rate-limited, or rotate keys if available."""
        if self.key_rotator and key_if_any:
            self.key_rotator.mark_limited(key_if_any)
            if self.key_rotator.has_active_keys():
                # We have more keys! Don't mark provider as limited yet.
                self.status = ProviderStatus.HEALTHY
                return

        self.status = ProviderStatus.RATE_LIMITED
        self.rate_limit_reset_at = time.time() + reset_after_seconds
        logging.warning(f"⚠️ [{self.name}] ALL KEYS EXHAUSTED — switching provider. Retry after {reset_after_seconds:.0f}s")

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


# ============================================================================
# Global registry to share KeyRotator instances across different ProviderManagers
# This ensures that if a key is rate-limited in 'Audio', the 'Document' manager knows it immediately.
_rotator_registry = {}

def get_shared_rotator(env_var_name: str) -> KeyRotator:
    """Helper to get or create a shared KeyRotator for a specific environment variable."""
    if env_var_name not in _rotator_registry:
        _rotator_registry[env_var_name] = KeyRotator(env_var_name)
    return _rotator_registry[env_var_name]

class ProviderManager:
    """
    Manages multiple inference providers with automatic failover.
    Thread-safe for use with Uvicorn workers.
    """

    def __init__(self, name: str = "default"):
        self._lock = threading.Lock()
        self.name = name
        
        if name == "ASR":
            self.providers = {
                "assemblyai": ProviderState(
                    name=f"AssemblyAI-{name}",
                    key_rotator=get_shared_rotator("ASSEMBLYAI_API_KEYS")
                ),
                "deepgram": ProviderState(
                    name=f"Deepgram-{name}",
                    key_rotator=get_shared_rotator("DEEPGRAM_API_KEYS")
                ),
            }
            self.priority_order = ["assemblyai", "deepgram"]
            
        elif name == "LLM-Document":
            # High-throughput chain for Document Intelligence (Gemini First, NO Ollama)
            self.providers = {
                "gemini": ProviderState(
                    name=f"Gemini-{name}", 
                    key_rotator=get_shared_rotator("GEMINI_API_KEYS")
                ),
                "groq": ProviderState(
                    name=f"Groq-{name}", 
                    key_rotator=get_shared_rotator("GROQ_API_KEYS")
                ),
                "huggingface": ProviderState(name=f"HuggingFace-{name}"),
            }
            self.priority_order = ["gemini", "groq", "huggingface"]

        elif name == "LLM-Generation":
            # High-throughput chain for Audio Synthesis (Groq First, includes Ollama)
            self.providers = {
                "groq": ProviderState(
                    name=f"Groq-{name}", 
                    key_rotator=get_shared_rotator("GROQ_API_KEYS")
                ),
                "gemini": ProviderState(
                    name=f"Gemini-{name}", 
                    key_rotator=get_shared_rotator("GEMINI_API_KEYS")
                ),
                "huggingface": ProviderState(name=f"HuggingFace-{name}"),
                "ollama": ProviderState(name=f"Ollama-{name}"),
            }
            self.priority_order = ["groq", "gemini", "huggingface", "ollama"]
            
        elif name == "LLM-Chat-Document":
            # Snappy, high-quality chain for Document Chat (Gemini First, NO Ollama)
            self.providers = {
                "gemini": ProviderState(
                    name=f"Gemini-{name}", 
                    key_rotator=get_shared_rotator("GEMINI_API_KEYS")
                ),
                "groq": ProviderState(
                    name=f"Groq-{name}", 
                    key_rotator=get_shared_rotator("GROQ_API_KEYS")
                ),
                "huggingface": ProviderState(name=f"HuggingFace-{name}"),
            }
            self.priority_order = ["gemini", "groq", "huggingface"]

        elif name == "LLM-Chat":
            # Snappy, low-latency chain for Conversational Chat
            self.providers = {
                "groq": ProviderState(
                    name=f"Groq-{name}", 
                    key_rotator=get_shared_rotator("GROQ_API_KEYS")
                ),
                "huggingface": ProviderState(name=f"HuggingFace-{name}"),
                "ollama": ProviderState(name=f"Ollama-{name}"),
            }
            self.priority_order = ["groq", "huggingface", "ollama"]
            
        else:
            # Default fallback for any other unnamed pool
            self.providers = {
                "groq": ProviderState(name=f"Groq-{name}"),
                "ollama": ProviderState(name=f"Ollama-{name}"),
            }
            self.priority_order = ["groq", "ollama"]
            
        logging.info(f"🧠 Provider Manager [{name}] initialized with chain: {' -> '.join(self.priority_order)}")

    def get_active_key(self, provider_name: str) -> str:
        """Retrieves the current active API key for a provider."""
        with self._lock:
            if provider_name in self.providers:
                state = self.providers[provider_name]
                if state.key_rotator:
                    key = state.key_rotator.get_key()
                    if key:
                        return key
            # Default to env if no rotator or no key returned
            env_map = {
                "groq": "GROQ_API_KEY", 
                "gemini": "GEMINI_API_KEY", 
                "huggingface": "HUGGING_FACE_ACCESS_TOKEN",
                "assemblyai": "ASSEMBLYAI_API_KEY",
                "deepgram": "DEEPGRAM_API_KEY"
            }
            key_name = env_map.get(provider_name, "")
            raw = os.getenv(key_name, "")
            if not raw and provider_name == "assemblyai":
                raw = os.getenv("ASSEMBLY_API_KEY", "")
            # Return first key if comma-separated
            keys = [k.strip() for k in raw.split(",") if k.strip()]
            return keys[0] if keys else ""

    def force_recover(self, provider_name: str):
        """Force a provider to recover to HEALTHY status."""
        with self._lock:
            if provider_name in self.providers:
                state = self.providers[provider_name]
                state.status = ProviderStatus.HEALTHY
                state.consecutive_failures = 0
                if state.key_rotator:
                    for k_state in state.key_rotator.key_states:
                        k_state.status = KeyStatus.ACTIVE
                        k_state.failure_count = 0
                logging.info(f"🔄 [{self.name}] Provider [{provider_name}] force-recovered to HEALTHY")

    def select_provider(self) -> str:
        """Select the best available provider based on priority and health."""
        with self._lock:
            for name in self.priority_order:
                state = self.providers[name]
                if state.is_available():
                    # If it has a key rotator, check if it has keys available
                    if state.key_rotator:
                        if state.key_rotator.has_active_keys():
                            return name
                        continue # No active keys for this provider, try next
                    return name

            # All cloud providers down — force fallback
            if self.name == "ASR":
                logging.warning("⚠️ All ASR providers unavailable — forcing Deepgram fallback")
                self.providers["deepgram"].status = ProviderStatus.HEALTHY
                return "deepgram"
            else:
                logging.warning("⚠️ ALL CLOUD PROVIDERS EXHAUSTED — ACTIVATING OLLAMA FALLBACK")
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

    def mark_rate_limited(self, provider_name: str, key_if_any: str = None, reset_after: float = 60.0):
        """Mark a provider as rate-limited."""
        with self._lock:
            if provider_name in self.providers:
                self.providers[provider_name].mark_rate_limited(key_if_any, reset_after)

    def get_active_providers(self) -> list:
        """Returns a list of provider names that are currently available, in priority order."""
        with self._lock:
            active = []
            for name in self.priority_order:
                state = self.providers[name]
                if state.is_available():
                    if state.key_rotator:
                        if state.key_rotator.has_active_keys():
                            active.append(name)
                    else:
                        active.append(name)
            return active

    def get_status_report(self) -> dict:
        """Get a snapshot of all provider statuses for monitoring."""
        with self._lock:
            return {
                name: {
                    "status": state.status.value,
                    "avg_latency_ms": round(state.avg_latency_ms, 1),
                    "consecutive_failures": state.consecutive_failures,
                    "total_requests": state.total_requests,
                    "keys_active": len([s for s in state.key_rotator.key_states if s.status == KeyStatus.ACTIVE]) if state.key_rotator else "N/A"
                }
                for name, state in self.providers.items()
            }

# Global singleton instance
provider_manager = ProviderManager(name="ASR")
