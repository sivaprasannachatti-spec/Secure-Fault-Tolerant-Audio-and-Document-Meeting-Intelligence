"""
LLM Service — Multi-provider LLM inference with automatic failover.

Supports two independent LLM pools:
  - Generation Pool (summary, actions, decisions, meeting titles):
      Groq qwen3-32b → HF Qwen3-8B → Local Ollama qwen3:8b
  
  - Chat Pool (conversational responses, chat titles):
      Groq llama-3.3-70b → HF Mistral-7B-Instruct → Local Ollama llama3.2:3b
"""

import os
import time
import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src.logger import logging
from src.providers.provider_manager import ProviderManager, ProviderStatus
from src.providers.health_monitor import health_monitor
import threading

# ─── Separate Provider Managers for each LLM pool ──────────────────────────

generation_provider_manager = ProviderManager(name="LLM-Generation")
chat_provider_manager = ProviderManager(name="LLM-Chat")

# Thread pool for blocking local Ollama calls
_llm_thread_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="llm-worker")

class DynamicConcurrencyManager:
    """Manages active local model requests to respect dynamic CPU limits."""
    def __init__(self):
        self.active_requests = 0
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        
    def acquire(self):
        with self._cond:
            while self.active_requests >= health_monitor.get_local_concurrency_limit():
                self._cond.wait(timeout=1.0)
            self.active_requests += 1
            
    def release(self):
        with self._cond:
            self.active_requests -= 1
            self._cond.notify()

_local_llm_manager = DynamicConcurrencyManager()


# ─── LLM Factory — returns the right model for the given provider ──────────

def _get_generation_llm(provider: str):
    """Get the LLM model for generation tasks based on provider."""
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model="qwen/qwen3-32b",
            api_key=os.environ.get("GROQ_API_KEY"),
            temperature=0.6,
        )
    elif provider == "huggingface":
        from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
        llm = HuggingFaceEndpoint(
            repo_id="Qwen/Qwen3-8B",
            huggingfacehub_api_token=os.environ.get("HUGGING_FACE_ACCESS_TOKEN"),
            task="text-generation",
            max_new_tokens=2048,
        )
        return ChatHuggingFace(llm=llm)
    else:
        from src.utils import QWEN_MODEL
        return QWEN_MODEL


def _get_chat_llm(provider: str):
    """Get the LLM model for chat tasks based on provider."""
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=os.environ.get("GROQ_API_KEY"),
            temperature=0.7,
        )
    elif provider == "huggingface":
        from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
        llm = HuggingFaceEndpoint(
            repo_id="mistralai/Mistral-7B-Instruct-v0.2",
            huggingfacehub_api_token=os.environ.get("HUGGING_FACE_ACCESS_TOKEN"),
            task="text-generation",
            max_new_tokens=2048,
        )
        return ChatHuggingFace(llm=llm)
    else:
        from src.utils import LLAMA_MODEL
        return LLAMA_MODEL


# ─── Core Inference Functions ──────────────────────────────────────────────

def invoke_generation(chain_builder, invoke_args: dict) -> str:
    """
    Execute a generation LLM call with automatic failover.
    
    Args:
        chain_builder: function(llm) -> chain  (builds prompt|llm|parser)
        invoke_args: dict of args to pass to chain.invoke()
    
    Returns:
        LLM output string or parsed result
    """
    last_error = None
    tried_providers = set()

    for attempt in range(3):
        provider = generation_provider_manager.select_provider()
        
        if provider in tried_providers:
            for fallback in generation_provider_manager.priority_order:
                if fallback not in tried_providers:
                    provider = fallback
                    break
            else:
                break
        
        tried_providers.add(provider)
        logging.info(f"🧠 Generation attempt {attempt + 1}/3 — using [{provider}]")

        try:
            start = time.monotonic()
            llm = _get_generation_llm(provider)
            chain = chain_builder(llm)
            
            if provider == "ollama":
                _local_llm_manager.acquire()
                try:
                    result = chain.invoke(invoke_args)
                finally:
                    _local_llm_manager.release()
            else:
                result = chain.invoke(invoke_args)
                
            latency_ms = (time.monotonic() - start) * 1000
            
            generation_provider_manager.record_success(provider, latency_ms)
            logging.info(f"✅ Generation completed via [{provider}] in {latency_ms:.0f}ms")
            return result

        except Exception as e:
            error_msg = str(e).lower()
            if "rate" in error_msg and "limit" in error_msg or "429" in error_msg:
                generation_provider_manager.mark_rate_limited(provider, 60.0)
                logging.warning(f"⚠️ [{provider}] rate limited for generation, trying next...")
            else:
                generation_provider_manager.record_failure(provider, type(e).__name__)
                logging.error(f"❌ [{provider}] generation failed: {e}")
            last_error = e
            continue

    raise Exception(f"All generation providers failed. Last error: {last_error}")


def invoke_chat(chain_builder, invoke_args: dict):
    """
    Execute a chat LLM call with automatic failover.
    Same pattern as invoke_generation but uses chat provider pool.
    """
    last_error = None
    tried_providers = set()

    for attempt in range(3):
        provider = chat_provider_manager.select_provider()
        
        if provider in tried_providers:
            for fallback in chat_provider_manager.priority_order:
                if fallback not in tried_providers:
                    provider = fallback
                    break
            else:
                break
        
        tried_providers.add(provider)
        logging.info(f"💬 Chat attempt {attempt + 1}/3 — using [{provider}]")

        try:
            start = time.monotonic()
            llm = _get_chat_llm(provider)
            chain = chain_builder(llm)
            
            if provider == "ollama":
                _local_llm_manager.acquire()
                try:
                    result = chain.invoke(invoke_args)
                finally:
                    _local_llm_manager.release()
            else:
                result = chain.invoke(invoke_args)
                
            latency_ms = (time.monotonic() - start) * 1000
            
            chat_provider_manager.record_success(provider, latency_ms)
            logging.info(f"✅ Chat completed via [{provider}] in {latency_ms:.0f}ms")
            return result

        except Exception as e:
            error_msg = str(e).lower()
            if "rate" in error_msg and "limit" in error_msg or "429" in error_msg:
                chat_provider_manager.mark_rate_limited(provider, 60.0)
            else:
                chat_provider_manager.record_failure(provider, type(e).__name__)
            last_error = e
            continue

    raise Exception(f"All chat providers failed. Last error: {last_error}")


def stream_chat(chain_builder, invoke_args: dict):
    """
    Stream a chat LLM response with automatic failover.
    Returns a generator that yields token chunks.
    Falls back to next provider if streaming fails before first token.
    """
    last_error = None
    tried_providers = set()

    for attempt in range(3):
        provider = chat_provider_manager.select_provider()
        
        if provider in tried_providers:
            for fallback in chat_provider_manager.priority_order:
                if fallback not in tried_providers:
                    provider = fallback
                    break
            else:
                break
        
        tried_providers.add(provider)
        logging.info(f"💬 Chat stream attempt {attempt + 1}/3 — using [{provider}]")

        try:
            start = time.monotonic()
            llm = _get_chat_llm(provider)
            chain = chain_builder(llm)
            
            first_token = True
            
            if provider == "ollama":
                _local_llm_manager.acquire()
                try:
                    for chunk in chain.stream(invoke_args):
                        if first_token:
                            latency_ms = (time.monotonic() - start) * 1000
                            chat_provider_manager.record_success(provider, latency_ms)
                            logging.info(f"⚡ First token via [{provider}] in {latency_ms:.0f}ms")
                            first_token = False
                        yield chunk
                finally:
                    _local_llm_manager.release()
            else:
                for chunk in chain.stream(invoke_args):
                    if first_token:
                        latency_ms = (time.monotonic() - start) * 1000
                        chat_provider_manager.record_success(provider, latency_ms)
                        logging.info(f"⚡ First token via [{provider}] in {latency_ms:.0f}ms")
                        first_token = False
                    yield chunk
                    
            return

        except Exception as e:
            error_msg = str(e).lower()
            if "rate" in error_msg and "limit" in error_msg or "429" in error_msg:
                chat_provider_manager.mark_rate_limited(provider, 60.0)
            else:
                chat_provider_manager.record_failure(provider, type(e).__name__)
            last_error = e
            continue

    raise Exception(f"All chat stream providers failed. Last error: {last_error}")
