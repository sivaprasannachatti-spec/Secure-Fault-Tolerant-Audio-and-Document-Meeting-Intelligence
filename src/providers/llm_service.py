"""
LLM Service — Multi-provider LLM inference with automatic failover.

Supports two independent LLM pools:
  - Generation Pool (summary, actions, decisions, meeting titles):
      Groq qwen3-32b -> HF Qwen3-8B -> Local Ollama qwen3:8b
  
  - Chat Pool (conversational responses, chat titles):
      Groq llama-3.3-70b -> HF Mistral-7B-Instruct -> Local Ollama llama3.2:3b
"""

import os
import time
import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv

# Optional HuggingFace Import
try:
    from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False

from src.logger import logging
from src.providers.provider_manager import ProviderManager, ProviderStatus
from src.providers.health_monitor import health_monitor
import threading

# --- Separate Provider Managers for each LLM pool --------------------------

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


# --- LLM Factory — returns the right model for the given provider ----------

def get_generation_model(provider: str, task_type: str = "summary"):
    """
    Returns a configured ChatModel based on provider and task.
    Optimized: Uses 'Instant' models for fast tasks to avoid rate limits.
    """
    if provider == "groq":
        # MODEL TIERING: Use 70B for Summary, 8B-Instant for Actions/Decisions
        model_name = "llama-3.3-70b-versatile" if task_type == "summary" else "llama-3.1-8b-instant"
        
        return ChatGroq(
            model=model_name,
            api_key=os.environ.get("GROQ_API_KEY"),
            temperature=0.6 if task_type == "summary" else 0.1,
            streaming=True,
        )
    elif provider == "huggingface":
        if not HF_AVAILABLE:
            raise ImportError("langchain-huggingface not installed. Please restart server.")
            
        llm = HuggingFaceEndpoint(
            repo_id="Qwen/Qwen2.5-7B-Instruct",
            huggingfacehub_api_token=os.environ.get("HUGGING_FACE_ACCESS_TOKEN"),
            task="text-generation",
            max_new_tokens=2048,
            streaming=True,
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
            streaming=True,
        )

    elif provider == "huggingface":
        if not HF_AVAILABLE:
            raise ImportError("langchain-huggingface not installed.")
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


def _clean_llm_output(text: str) -> str:
    """
    Cleans the LLM output by removing reasoning tags (<think>...</think>)
    and extracting only the valid JSON block if present.
    """
    import re
    # 1. Remove reasoning tags and their content
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    
    # 2. Extract JSON block if it exists (look for { ... })
    json_match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
    if json_match:
        return json_match.group(0)
    
    return text.strip()


# --- Core Inference Functions ----------------------------------------------

def invoke_generation(chain_builder, invoke_args: dict) -> str:
    """
    Execute a generation LLM call with automatic failover.
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
        logging.info("--------------------------------------------------")
        logging.info(f"GENERATION ROUTING -> USING PROVIDER: [{provider.upper()}]")
        logging.info("--------------------------------------------------")

        try:
            start = time.monotonic()
            llm = get_generation_model(provider)
            chain = chain_builder(llm)
            
            if provider == "ollama":
                _local_llm_manager.acquire()
                try:
                    result = chain.invoke(invoke_args)
                finally:
                    _local_llm_manager.release()
            else:
                try:
                    result = chain.invoke(invoke_args)
                except Exception as e:
                    error_str = str(e)
                    if "invalid json" in error_str.lower() or "parsing" in error_str.lower():
                        logging.warning(f"[WARN] [{provider}] parsing failed, attempting recovery...")
                        
                        output = None
                        if hasattr(e, 'llm_output'):
                            output = e.llm_output
                        elif "got:" in error_str:
                            output = error_str.split("got:")[1]
                        
                        if output:
                            cleaned_output = _clean_llm_output(output)
                            if hasattr(chain, 'last'):
                                parser = chain.last
                                result = parser.parse(cleaned_output)
                                logging.info(f"[INFO] Recovered from [{provider}] parsing error.")
                            else:
                                raise e
                        else:
                            raise e
                    else:
                        raise e

            latency_ms = (time.monotonic() - start) * 1000
            generation_provider_manager.record_success(provider, latency_ms)
            logging.info(f"[OK] Generation completed via [{provider}] in {latency_ms:.0f}ms")
            return result

        except Exception as e:
            error_msg = str(e).lower()
            if "rate" in error_msg and "limit" in error_msg or "429" in error_msg:
                generation_provider_manager.mark_rate_limited(provider, 60.0)
                logging.warning(f"[WARN] [{provider}] rate limited, trying next...")
            else:
                generation_provider_manager.record_failure(provider, type(e).__name__)
                logging.error(f"[ERROR] [{provider}] generation failed: {e}")
            last_error = e
            continue

    raise Exception(f"All generation providers failed. Last error: {last_error}")


def stream_generation(chain_builder, invoke_args: dict, task_type: str = "summary"):
    """
    Generator that handles multi-provider failover with REAL-TIME STREAMING.
    """
    providers = generation_provider_manager.get_active_providers()
    
    for provider in providers:
        try:
            print(f"[STREAM] ROUTING -> {provider.upper()} ({task_type})")
            
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    llm = get_generation_model(provider, task_type=task_type)
                    chain = chain_builder(llm)
                    
                    full_content = []
                    start = time.monotonic()
                    first_token = True
                    is_thinking = False
                    
                    if provider == "ollama":
                        _local_llm_manager.acquire()
                        try:
                            for chunk in chain.stream(invoke_args):
                                if first_token:
                                    latency_ms = (time.monotonic() - start) * 1000
                                    generation_provider_manager.record_success(provider, latency_ms)
                                    first_token = False
                                
                                text = chunk if isinstance(chunk, str) else getattr(chunk, 'content', str(chunk))
                                if "<think>" in text: is_thinking = True
                                yield (is_thinking, text.replace("<think>", "").replace("</think>", ""))
                                full_content.append(text)
                                if "</think>" in text: is_thinking = False
                        finally:
                            _local_llm_manager.release()
                    else:
                        for chunk in chain.stream(invoke_args):
                            if first_token:
                                latency_ms = (time.monotonic() - start) * 1000
                                generation_provider_manager.record_success(provider, latency_ms)
                                first_token = False
                            
                            text = chunk if isinstance(chunk, str) else getattr(chunk, 'content', str(chunk))
                            if "<think" in text: is_thinking = True
                            clean_text = text.replace("<think>", "").replace("</think>", "")
                            if clean_text:
                                yield (is_thinking, clean_text)
                                full_content.append(clean_text)
                            if "</think>" in text: is_thinking = False
                    return
                except Exception as e:
                    if ("rate" in str(e).lower() or "429" in str(e)) and attempt < max_retries - 1:
                        print(f"  [WARN] Groq Rate Limit. Retrying in 2s...")
                        time.sleep(2)
                        continue
                    raise e
        except Exception as e:
            logging.error(f"[ERROR] [{provider}] stream failed: {e}")
            continue

    raise Exception("All generation stream providers failed.")


async def astream_generation(chain_builder, invoke_args: dict, task_type: str = "summary"):
    """
    Async generator for real-time streaming with intelligent task-routing.
    """
    providers = generation_provider_manager.get_active_providers()
    
    for provider in providers:
        try:
            print(f"[ASYNC STREAM] ROUTING -> {provider.upper()} ({task_type})")
            
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    llm = get_generation_model(provider, task_type=task_type)
                    chain = chain_builder(llm)
                    
                    start = time.monotonic()
                    first_token = True
                    is_thinking = False
                    
                    if provider == "ollama":
                        async with asyncio.Lock(): 
                            async for chunk in chain.astream(invoke_args):
                                if first_token:
                                    latency_ms = (time.monotonic() - start) * 1000
                                    generation_provider_manager.record_success(provider, latency_ms)
                                    first_token = False
                                
                                text = chunk if isinstance(chunk, str) else getattr(chunk, 'content', str(chunk))
                                if "<think>" in text: is_thinking = True
                                yield (is_thinking, text.replace("<think>", "").replace("</think>", ""))
                                if "</think>" in text: is_thinking = False
                    else:
                        async for chunk in chain.astream(invoke_args):
                            if first_token:
                                latency_ms = (time.monotonic() - start) * 1000
                                generation_provider_manager.record_success(provider, latency_ms)
                                first_token = False
                            
                            text = chunk if isinstance(chunk, str) else getattr(chunk, 'content', str(chunk))
                            if "<think" in text: is_thinking = True
                            clean_text = text.replace("<think>", "").replace("</think>", "")
                            if clean_text:
                                yield (is_thinking, clean_text)
                            if "</think>" in text: is_thinking = False
                    return
                except Exception as e:
                    if ("rate" in str(e).lower() or "429" in str(e)) and attempt < max_retries - 1:
                        print(f"  [WARN] Groq Rate Limit. Retrying in 2s...")
                        await asyncio.sleep(2)
                        continue
                    raise e
        except Exception as e:
            logging.error(f"[ERROR] [{provider}] async stream failed: {e}")
            continue

    raise Exception("All async generation stream providers failed.")


def invoke_chat(chain_builder, invoke_args: dict):
    """
    Execute a chat LLM call with automatic failover.
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
        logging.info("--------------------------------------------------")
        logging.info(f"CHAT ROUTING -> USING PROVIDER: [{provider.upper()}]")
        logging.info("--------------------------------------------------")

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
            logging.info(f"[OK] Chat completed via [{provider}] in {latency_ms:.0f}ms")
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
        logging.info("--------------------------------------------------")
        logging.info(f"CHAT STREAM ROUTING -> USING PROVIDER: [{provider.upper()}]")
        logging.info("--------------------------------------------------")

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
                            logging.info(f"[SPEED] First token via [{provider}] in {latency_ms:.0f}ms")
                            first_token = False
                        yield chunk
                finally:
                    _local_llm_manager.release()
            else:
                for chunk in chain.stream(invoke_args):
                    if first_token:
                        latency_ms = (time.monotonic() - start) * 1000
                        chat_provider_manager.record_success(provider, latency_ms)
                        logging.info(f"[SPEED] First token via [{provider}] in {latency_ms:.0f}ms")
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
