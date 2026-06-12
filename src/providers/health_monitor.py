"""
Health Monitor — Background service that monitors provider health
and auto-recovers failed providers.

Runs as an asyncio background task during the FastAPI lifespan.
Uses exponential backoff to avoid hammering failed providers.
"""

import os
import asyncio
import aiohttp
import time
import psutil

from src.logger import logging
from src.providers.provider_manager import provider_manager, ProviderStatus


class HealthMonitor:
    """
    Periodically pings all providers and recovers them when they come back online.
    Monitors all provider manager pools (ASR, Generation, Chat).
    Also tracks system resources to dynamically limit local model concurrency.
    """

    def __init__(self, check_interval: float = 30.0, max_backoff: float = 300.0):
        self.check_interval = check_interval
        self.max_backoff = max_backoff
        self._running = False
        self._task = None
        self._managers = []  # List of all ProviderManager instances to monitor
        self._backoff = {}   # Track backoff per manager+provider combo
        
        # System resource tracking
        self.current_cpu_percent = 0.0
        self.current_memory_percent = 0.0
        self._max_cpu_cores = psutil.cpu_count(logical=True) or 4

    def register_manager(self, manager):
        """Register a ProviderManager instance for health monitoring."""
        self._managers.append(manager)
        for provider_name in manager.providers:
            key = f"{manager.name}:{provider_name}"
            self._backoff[key] = 0
        logging.info(f"💓 Registered [{manager.name}] pool for health monitoring")

    async def start(self):
        """Start the health monitor as a background task."""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logging.info(f"💓 Health Monitor started — tracking {len(self._managers)} pools (every {self.check_interval:.0f}s)")

    async def stop(self):
        """Gracefully stop the health monitor."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logging.info("💓 Health Monitor stopped")

    def get_local_concurrency_limit(self) -> int:
        """
        Dynamically calculate safe concurrency for local models (Whisper/Ollama)
        based on current CPU/Memory load.
        """
        # If CPU > 85% or RAM > 90%, restrict to 1 thread
        if self.current_cpu_percent > 85.0 or self.current_memory_percent > 90.0:
            return 1
            
        # If CPU > 60%, restrict to half cores
        if self.current_cpu_percent > 60.0:
            return max(1, self._max_cpu_cores // 4)
            
        # Idle/Low load: Use half cores, min 2
        return max(2, self._max_cpu_cores // 2)

    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                # Update system metrics
                self.current_cpu_percent = psutil.cpu_percent(interval=None)
                self.current_memory_percent = psutil.virtual_memory().percent
                
                await self._check_all_providers()
            except Exception as e:
                logging.error(f"Health monitor error: {e}")
            await asyncio.sleep(self.check_interval)

    async def _check_all_providers(self):
        """Check all unhealthy providers across all manager pools."""
        for manager in self._managers:
            # We track all cloud providers and ollama
            for name in ["groq", "huggingface", "assemblyai", "deepgram", "ollama"]:
                state = manager.providers.get(name)
                if not state:
                    continue

                if state.status in (ProviderStatus.DOWN, ProviderStatus.RATE_LIMITED):
                    key = f"{manager.name}:{name}"
                    backoff_count = self._backoff.get(key, 0)
                    wait_time = min(2 ** backoff_count * self.check_interval, self.max_backoff)

                    time_since_failure = time.time() - state.last_failure_time
                    if time_since_failure < wait_time:
                        continue

                    logging.info(f"🔄 [{manager.name}] Health check: pinging [{name}]...")
                    is_healthy = await self._ping_provider(name)

                    if is_healthy:
                        manager.force_recover(name)
                        self._backoff[key] = 0
                    else:
                        self._backoff[key] = min(backoff_count + 1, 8)

    async def _ping_provider(self, name: str) -> bool:
        """Send a lightweight health check to a provider."""
        try:
            if name == "groq":
                return await self._ping_groq()
            elif name == "huggingface":
                return await self._ping_huggingface()
            elif name == "assemblyai":
                return await self._ping_assemblyai()
            elif name == "deepgram":
                return await self._ping_deepgram()
            elif name == "ollama":
                return await self._ping_local()
        except Exception as e:
            logging.debug(f"Health check failed for [{name}]: {e}")
            return False

    async def _ping_groq(self) -> bool:
        """Check if Groq API is responsive."""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {os.environ.get('GROQ_API_KEY')}",
                }
                async with session.get(
                    "https://api.groq.com/openai/v1/models",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status == 200
        except:
            return False

    async def _ping_huggingface(self) -> bool:
        """Check if HuggingFace inference endpoint is responsive."""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {os.environ.get('HUGGING_FACE_ACCESS_TOKEN')}",
                }
                async with session.get(
                    "https://huggingface.co/api/models/Qwen/Qwen3-8B",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status == 200
        except:
            return False

    async def _ping_assemblyai(self) -> bool:
        """Check if AssemblyAI API is responsive."""
        try:
            api_key = provider_manager.get_active_key("assemblyai")
            if not api_key:
                return False
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": api_key}
                async with session.get(
                    "https://api.assemblyai.com/v2/account",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status == 200
        except:
            return False

    async def _ping_deepgram(self) -> bool:
        """Check if Deepgram API is responsive."""
        try:
            api_key = provider_manager.get_active_key("deepgram")
            if not api_key:
                return False
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Token {api_key}"}
                async with session.get(
                    "https://api.deepgram.com/v1/projects",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status == 200
        except:
            return False
            
    async def _ping_local(self) -> bool:
        """Check if local inference environment is responsive. Ollama is used as a proxy."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "http://localhost:11434/api/tags",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    return resp.status == 200
        except:
            return False


# Global singleton
health_monitor = HealthMonitor()
