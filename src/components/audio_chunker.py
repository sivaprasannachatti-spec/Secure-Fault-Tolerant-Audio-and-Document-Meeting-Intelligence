import io
import numpy as np
import soundfile as sf
import tempfile
import os
import sys
from typing import List, Dict

from src.logger import logging
from src.exception import CustomException

class AudioChunker:
    """
    Handles chunking of audio for processing large files.
    Ensures that chunks are kept in memory to prevent repeated I/O
    and preprocessing during failovers.
    """
    
    def __init__(self, chunk_duration_sec: int = 60, overlap_sec: int = 2):
        self.chunk_duration_sec = chunk_duration_sec
        self.overlap_sec = overlap_sec

    def split_audio_into_chunks(self, audio_bytes: bytes) -> List[Dict[str, any]]:
        """
        Splits a 16kHz Mono WAV byte string into smaller chunk bytes.
        Returns a list of dictionaries containing the chunk bytes and metadata.
        """
        if not audio_bytes:
            raise CustomException("Empty audio bytes provided for chunking.", sys)

        temp_path = None
        try:
            # Write to temp file for librosa to read cleanly
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
                temp_file.write(audio_bytes)
                temp_path = temp_file.name

            # Load audio using soundfile (much lighter than librosa)
            audio, sr = sf.read(temp_path)
            
            # Convert to mono if stereo
            if len(audio.shape) > 1:
                audio = np.mean(audio, axis=1)
                
            # Resample to 16000Hz using numpy interpolation if needed
            if sr != 16000:
                duration = len(audio) / sr
                num_samples = int(duration * 16000)
                audio = np.interp(
                    np.linspace(0, len(audio) - 1, num_samples),
                    np.arange(len(audio)),
                    audio
                )
                sr = 16000
                
            total_duration = len(audio) / sr
            logging.info(f"Chunking audio: {total_duration:.2f}s total duration.")

            chunks = []
            chunk_length_samples = self.chunk_duration_sec * sr
            overlap_samples = self.overlap_sec * sr
            
            start_sample = 0
            chunk_index = 0

            while start_sample < len(audio):
                end_sample = min(start_sample + chunk_length_samples, len(audio))
                chunk_audio = audio[start_sample:end_sample]
                
                # Convert back to bytes
                output_buffer = io.BytesIO()
                sf.write(output_buffer, chunk_audio, sr, format='WAV')
                chunk_bytes = output_buffer.getvalue()

                chunk_start_sec = start_sample / sr
                chunk_end_sec = end_sample / sr

                chunks.append({
                    "index": chunk_index,
                    "bytes": chunk_bytes,
                    "start_time": chunk_start_sec,
                    "end_time": chunk_end_sec
                })

                logging.info(f"Created chunk {chunk_index}: {chunk_start_sec:.1f}s - {chunk_end_sec:.1f}s ({len(chunk_bytes)} bytes)")

                # If we've reached the end, stop
                if end_sample == len(audio):
                    break

                # Advance start_sample, stepping back by overlap
                start_sample = end_sample - overlap_samples
                chunk_index += 1

            return chunks

        except Exception as e:
            raise CustomException(e, sys)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

# Singleton instance
audio_chunker = AudioChunker()
