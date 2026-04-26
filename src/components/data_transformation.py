import librosa
import numpy as np
import noisereduce as nr
import soundfile as sf
import io
import os
import sys
import tempfile
from src.exception import CustomException
from src.logger import logging

class DataTransformation():
    def preprocess_audio(self, audio_bytes: bytes) -> bytes:
        """
        Accepts raw audio bytes (any format), preprocesses them, 
        and returns cleaned audio bytes strictly in WAV format.
        """
        # Fix 1: Guard against completely empty file uploads
        if not audio_bytes or len(audio_bytes) == 0:
            raise CustomException("Empty audio file received", sys)

        temp_path = None
        try:
            # Fix 2: Write input bytes to a temp file without a specific suffix.
            # This prevents librosa from getting confused if the file is an MP3.
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(audio_bytes)
                temp_path = temp_file.name

            audio, sr = librosa.load(temp_path, sr=16000, mono=True)
            logging.info(f"Audio loaded successfully. Duration: {len(audio)/sr:.2f}s")

            # Guard: Check if the original audio is too short before we do anything
            if len(audio) < sr * 1:
                raise CustomException("Uploaded audio is too short (< 1 second) to process.", sys)

            # Fix 3: Estimate noise BEFORE trimming (first 0.5s is usually room ambience)
            noise_sample = audio[:int(sr * 0.5)]

            # 4. Trim silence from start and end
            audio, _ = librosa.effects.trim(audio, top_db=25)
            logging.info("Silence trimmed successfully.")

            # Fix 4: If trimming removed the entire audio, raise error instead of returning None
            if len(audio) < sr * 1:
                raise CustomException("Audio too short after trimming silence.", sys)

            # 5. Skip SNR/Noise reduction for speed optimization
            logging.info("Skipping noise reduction to speed up processing.")

            # 6. Normalize safely
            max_val = np.max(np.abs(audio))
            if max_val > 0:
                audio = audio / max_val

            # 7. Convert the processed numpy array back to raw bytes (WAV format)
            output_buffer = io.BytesIO()
            sf.write(output_buffer, audio, sr, format='WAV')
            cleaned_bytes = output_buffer.getvalue()

            logging.info(f"Audio preprocessing complete. Output size: {len(cleaned_bytes)} bytes")
            return cleaned_bytes

        except Exception as e:
            raise CustomException(e, sys)
        
        finally:
            # Fix 5: ALWAYS clean up the temp file, even if an exception occurs mid-processing
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
