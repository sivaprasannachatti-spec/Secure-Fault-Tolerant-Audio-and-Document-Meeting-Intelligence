"""
ASR Service — Fast audio transcription and diarization using AssemblyAI.
Falls back to Deepgram Nova-3 if AssemblyAI fails or runs out of credits.
"""

import os
import time
import asyncio
import httpx

from src.logger import logging
from src.providers.provider_manager import provider_manager
from src.exception import CustomException
import sys

# We reuse the ASR provider manager (AssemblyAI -> Deepgram)
asr_provider_manager = provider_manager

async def _invoke_assemblyai(audio_bytes: bytes) -> str:
    """Upload and transcribe via AssemblyAI Universal-1 with Diarization."""
    api_key = asr_provider_manager.get_active_key("assemblyai")
    if not api_key:
        raise ValueError("ASSEMBLYAI_API_KEY / ASSEMBLY_API_KEY is not set.")
        
    headers = {"authorization": api_key}
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        # 1. Upload audio
        upload_resp = await client.post(
            "https://api.assemblyai.com/v2/upload",
            headers=headers,
            content=audio_bytes
        )
        if upload_resp.status_code != 200:
            if upload_resp.status_code == 402:
                raise Exception("402 Payment Required: AssemblyAI out of credits.")
            raise Exception(f"AssemblyAI upload failed: {upload_resp.text}")
            
        upload_url = upload_resp.json()["upload_url"]
        
        # 2. Start transcription job
        transcribe_resp = await client.post(
            "https://api.assemblyai.com/v2/transcript",
            headers=headers,
            json={
                "audio_url": upload_url,
                "speech_model": "best",  # Universal-1
                "speaker_labels": True
            }
        )
        if transcribe_resp.status_code != 200:
            raise Exception(f"AssemblyAI start failed: {transcribe_resp.text}")
            
        transcript_id = transcribe_resp.json()["id"]
        
        # 3. Poll for completion
        while True:
            poll_resp = await client.get(
                f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
                headers=headers
            )
            status = poll_resp.json()["status"]
            
            if status == "completed":
                # Build formatted transcript
                words = poll_resp.json().get("words", [])
                if not words:
                    return ""
                
                final_transcript = []
                current_speaker = words[0]["speaker"]
                current_text = []
                
                for word in words:
                    if word["speaker"] != current_speaker:
                        final_transcript.append(f"SPEAKER_{current_speaker}: {' '.join(current_text)}")
                        current_speaker = word["speaker"]
                        current_text = [word["text"]]
                    else:
                        current_text.append(word["text"])
                
                final_transcript.append(f"SPEAKER_{current_speaker}: {' '.join(current_text)}")
                return "\n".join(final_transcript)
                
            elif status == "error":
                raise Exception(f"AssemblyAI processing error: {poll_resp.json()['error']}")
                
            await asyncio.sleep(3)


async def _invoke_deepgram(audio_bytes: bytes) -> str:
    """Transcribe via Deepgram Nova-3 with Diarization."""
    api_key = asr_provider_manager.get_active_key("deepgram")
    if not api_key:
        raise ValueError("DEEPGRAM_API_KEY is not set.")
        
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "audio/wav"
    }
    
    params = {
        "model": "nova-3",
        "diarize": "true",
        "punctuate": "true"
    }
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            "https://api.deepgram.com/v1/listen",
            headers=headers,
            params=params,
            content=audio_bytes
        )
        
        if resp.status_code != 200:
            if resp.status_code == 402 or resp.status_code == 403:
                raise Exception("402/403 Payment Required: Deepgram out of credits.")
            raise Exception(f"Deepgram failed: {resp.text}")
            
        data = resp.json()
        try:
            paragraphs = data["results"]["channels"][0]["alternatives"][0]["paragraphs"]["paragraphs"]
            final_transcript = []
            for p in paragraphs:
                speaker = p["speaker"]
                text = " ".join([word["punctuated_word"] for sent in p["sentences"] for word in sent["words"]])
                final_transcript.append(f"SPEAKER_{speaker}: {text}")
            return "\n".join(final_transcript)
        except KeyError:
            # Fallback if diarization data structure is slightly different or missing
            return data["results"]["channels"][0]["alternatives"][0]["transcript"]


async def transcribe_audio_full(audio_bytes: bytes) -> str:
    """
    Transcribe and diarize audio using AssemblyAI or Deepgram with automatic failover.
    """
    last_error = None
    tried_providers = set()

    file_size_mb = len(audio_bytes) / (1024 * 1024)
    logging.info(f"🎤 ASR request — full audio size: {file_size_mb:.1f}MB")

    for attempt in range(3):
        provider = asr_provider_manager.select_provider()
        
        if provider in tried_providers:
            for fallback in asr_provider_manager.priority_order:
                if fallback not in tried_providers:
                    provider = fallback
                    break
            else:
                break
        
        tried_providers.add(provider)
        logging.info(f"==================================================")
        logging.info(f"🎤 ASR ROUTING -> USING PROVIDER: [{provider.upper()}]")
        logging.info(f"==================================================")

        api_key = None
        try:
            start = time.monotonic()
            api_key = asr_provider_manager.get_active_key(provider)
            if provider == "assemblyai":
                transcript = await _invoke_assemblyai(audio_bytes)
            elif provider == "deepgram":
                transcript = await _invoke_deepgram(audio_bytes)
            else:
                raise ValueError(f"Unknown ASR provider: {provider}")
                
            latency_ms = (time.monotonic() - start) * 1000
            asr_provider_manager.record_success(provider, latency_ms)
            logging.info(f"✅ ASR completed via [{provider.upper()}] in {latency_ms:.0f}ms")
            
            return transcript

        except Exception as e:
            error_msg = str(e).lower()
            if "rate limit" in error_msg or "429" in error_msg or "402" in error_msg or "payment required" in error_msg or "403" in error_msg:
                asr_provider_manager.mark_rate_limited(provider, key_if_any=api_key, reset_after=300.0) # wait 5 minutes if out of credits
                logging.warning(f"⚠️ [{provider}] rate limited or out of credits, switching provider...")
            else:
                asr_provider_manager.record_failure(provider, type(e).__name__)
                logging.error(f"❌ [{provider}] ASR failed: {e}")
            last_error = e
            continue

    raise Exception(f"All ASR providers failed. Last error: {last_error}")
