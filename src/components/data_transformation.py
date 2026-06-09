import numpy as np
import soundfile as sf
import io
import os
import sys
import tempfile
from src.exception import CustomException
from src.logger import logging

def resample_audio(audio, orig_sr, target_sr=16000):
    if orig_sr == target_sr:
        return audio
    duration = len(audio) / orig_sr
    num_samples = int(duration * target_sr)
    return np.interp(
        np.linspace(0, len(audio) - 1, num_samples),
        np.arange(len(audio)),
        audio
    )

def trim_silence_numpy(audio, top_db=25, frame_length=2048, hop_length=512):
    threshold = 10 ** (-top_db / 20)
    num_frames = (len(audio) - frame_length) // hop_length + 1
    if num_frames <= 0:
        return audio, (0, len(audio))
        
    rms = np.zeros(num_frames)
    for i in range(num_frames):
        start = i * hop_length
        end = start + frame_length
        rms[i] = np.sqrt(np.mean(audio[start:end] ** 2))
        
    active = np.where(rms > threshold)[0]
    if len(active) == 0:
        return audio, (0, len(audio))
        
    start_sample = active[0] * hop_length
    end_sample = min((active[-1] * hop_length) + frame_length, len(audio))
    return audio[start_sample:end_sample], (start_sample, end_sample)

class DataTransformation():
    def preprocess_audio(self, audio_bytes: bytes) -> bytes:
        """
        Accepts raw audio bytes (any format), preprocesses them, 
        and returns cleaned audio bytes strictly in WAV format.
        """
        if not audio_bytes or len(audio_bytes) == 0:
            raise CustomException("Empty audio file received", sys)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(audio_bytes)
                temp_path = temp_file.name

            # Load audio using soundfile (much lighter than librosa)
            audio, sr = sf.read(temp_path)
            
            # Convert to mono if stereo
            if len(audio.shape) > 1:
                audio = np.mean(audio, axis=1)
                
            # Resample to 16000Hz using numpy interpolation
            audio = resample_audio(audio, sr, 16000)
            sr = 16000
            
            logging.info(f"Audio loaded successfully. Duration: {len(audio)/sr:.2f}s")

            if len(audio) < sr * 1:
                raise CustomException("Uploaded audio is too short (< 1 second) to process.", sys)

            # Trim silence from start and end using pure numpy
            audio, _ = trim_silence_numpy(audio, top_db=25)
            logging.info("Silence trimmed successfully.")

            if len(audio) < sr * 1:
                raise CustomException("Audio too short after trimming silence.", sys)

            logging.info("Skipping noise reduction to speed up processing.")

            # Normalize safely
            max_val = np.max(np.abs(audio))
            if max_val > 0:
                audio = audio / max_val

            # Convert the processed numpy array back to raw bytes (WAV format)
            output_buffer = io.BytesIO()
            sf.write(output_buffer, audio, sr, format='WAV')
            cleaned_bytes = output_buffer.getvalue()

            logging.info(f"Audio preprocessing complete. Output size: {len(cleaned_bytes)} bytes")
            return cleaned_bytes

        except Exception as e:
            raise CustomException(e, sys)
        
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
