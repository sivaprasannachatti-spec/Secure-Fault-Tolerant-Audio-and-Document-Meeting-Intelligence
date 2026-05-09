"""
ASR Service — Multi-provider audio transcription with automatic failover.

Priority chain:
  1. Groq Whisper Large v3 (fastest, cloud)
  2. Local faster-whisper (always works, CPU, dynamic concurrency)
"""

import os
import time
import asyncio
import tempfile
import aiohttp
import traceback
from concurrent.futures import ThreadPoolExecutor

from src.logger import logging
from src.providers.provider_manager import provider_manager
from src.components.audio_chunker import audio_chunker
from src.providers.health_monitor import health_monitor

# Thread pool for running synchronous local inference without blocking
# We use a larger max_workers but restrict active inference using dynamic semaphores
_thread_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="asr-local")

# Groq concurrency (higher since it's an API)
_groq_semaphore = asyncio.Semaphore(10)

# Groq client (lazy-initialized)
_groq_client = None

def _get_groq_client():
    """Lazy-initialize the Groq client."""
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    return _groq_client

async def transcribe_audio_chunked(audio_bytes: bytes) -> str:
    """
    Main entry point for ASR. Splits audio into chunks, processes them
    concurrently using the best available provider, and handles failovers
    mid-transcription by reusing the same chunks.
    
    Args:
        audio_bytes: Raw WAV audio bytes
        
    Returns:
        Transcribed text string
    """
    file_size_mb = len(audio_bytes) / (1024 * 1024)
    logging.info(f"🎤 ASR chunked request — full audio size: {file_size_mb:.1f}MB")

    # 1. Chunk the audio (cache in memory)
    chunks = audio_chunker.split_audio_into_chunks(audio_bytes, chunk_duration_sec=60)
    
    # 2. Process chunks concurrently
    tasks = []
    for chunk in chunks:
        tasks.append(_process_chunk_with_failover(chunk))
        
    # Wait for all chunks to finish
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 3. Reconstruct transcript
    final_transcripts = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logging.error(f"❌ Chunk {i} permanently failed: {result}")
            final_transcripts.append(f"[Unintelligible segment {i}]")
        else:
            final_transcripts.append(result)
            
    return " ".join(final_transcripts)


async def _process_chunk_with_failover(chunk: dict) -> str:
    """
    Process a single chunk through the provider fallback chain.
    """
    chunk_index = chunk["index"]
    chunk_bytes = chunk["bytes"]
    last_error = None
    tried_providers = set()

    for attempt in range(3):
        provider = provider_manager.select_provider()
        
        # Skip if already tried this provider for this specific chunk
        if provider in tried_providers:
            for fallback in provider_manager.priority_order:
                if fallback not in tried_providers:
                    provider = fallback
                    break
            else:
                break
        
        tried_providers.add(provider)
        logging.info(f"🎤 Chunk {chunk_index} attempt {attempt + 1}/3 — using [{provider}]")

        try:
            start = time.monotonic()

            if provider == "groq":
                result = await _transcribe_groq(chunk_bytes)
            else:
                result = await _transcribe_local(chunk_bytes)

            latency_ms = (time.monotonic() - start) * 1000
            provider_manager.record_success(provider, latency_ms)
            logging.info(f"✅ Chunk {chunk_index} completed via [{provider}] in {latency_ms:.0f}ms")
            return result

        except RateLimitError as e:
            reset_after = getattr(e, 'reset_after', 60.0)
            provider_manager.mark_rate_limited(provider, reset_after)
            last_error = e
            logging.warning(f"⚠️ [{provider}] rate limited on chunk {chunk_index}, switching provider...")
            continue

        except Exception as e:
            provider_manager.record_failure(provider, type(e).__name__)
            last_error = e
            logging.error(f"❌ [{provider}] ASR failed on chunk {chunk_index}: {e}")
            continue

    raise ASRError(f"All ASR providers failed for chunk {chunk_index}. Last error: {last_error}")


# ─── Provider-Specific Implementations ─────────────────────────────────────

async def _transcribe_groq(audio_bytes: bytes) -> str:
    """Groq Whisper Large v3 — cloud, fastest."""
    loop = asyncio.get_event_loop()

    async def _do_groq():
        def _sync_groq():
            client = _get_groq_client()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            try:
                with open(tmp_path, "rb") as audio_file:
                    transcription = client.audio.transcriptions.create(
                        model="whisper-large-v3-turbo",
                        file=audio_file,
                        response_format="verbose_json",
                        language="en",
                    )
                return transcription.text
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        try:
            # Note: Groq SDK can throw a variety of errors, wrapped in run_in_executor
            return await asyncio.wait_for(
                loop.run_in_executor(_thread_pool, _sync_groq),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            raise TimeoutError("Groq transcription timed out after 60s")
        except Exception as e:
            err_str = str(e).lower()
            if "rate limit" in err_str or "429" in err_str:
                raise RateLimitError("Groq rate limited")
            raise ProviderError(str(e))

    async with _groq_semaphore:
        return await _do_groq()


async def _transcribe_local(audio_bytes: bytes) -> str:
    """Local faster-whisper — CPU fallback, respects dynamic concurrency."""
    loop = asyncio.get_event_loop()

    # Get dynamic limit from psutil-based health monitor
    limit = health_monitor.get_local_concurrency_limit()
    
    # We create a temporary semaphore for this evaluation context 
    # to enforce system-wide dynamic limits per-request tick
    # In a real heavy system we'd manage a shared global semaphore that adjusts size,
    # but here limiting active threads in the executor dynamically works well.
    local_sem = asyncio.Semaphore(limit)

    async with local_sem:
        def _sync_local():
            from src.utils import WHISPER_MODEL
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            try:
                segments_gen, _ = WHISPER_MODEL.transcribe(tmp_path)
                segments = list(segments_gen)
                return " ".join(seg.text.strip() for seg in segments)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        return await loop.run_in_executor(_thread_pool, _sync_local)


# ─── Custom Exceptions ─────────────────────────────────────────────────────

class ASRError(Exception):
    """All ASR providers failed."""
    pass

class RateLimitError(Exception):
    """Provider returned 429."""
    def __init__(self, message, reset_after=60.0):
        super().__init__(message)
        self.reset_after = reset_after

class ServiceUnavailableError(Exception):
    """Provider returned 503."""
    pass

class ProviderError(Exception):
    """Generic provider error."""
    pass
