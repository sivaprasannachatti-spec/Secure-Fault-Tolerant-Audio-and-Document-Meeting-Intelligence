import sys
import librosa
import os
import torch
import traceback
import tempfile

from faster_whisper import WhisperModel
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field
from langchain_classic.output_parsers import StructuredOutputParser, ResponseSchema, PydanticOutputParser
from src.exception import CustomException
from src.logger import logging
from pyannote.audio import Pipeline
from pyannote.core import Segment
from src.prompts.prompts import getPrompts
from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq
from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from src.output_parsers import generate_structured_outputs
from src.meeting_state import state

load_dotenv()

# Global LLM Instances for speed and memory persistence
QWEN_MODEL = ChatOllama(model='qwen3:8b', keep_alive=-1)
PHI_MODEL = ChatOllama(model='phi4-mini', keep_alive=-1)

# Global Model Loading (Initialized once on startup)
print("📦 Loading AI Models (Whisper & Diarization)...")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"🖥️ Using device: {device}")

compute_type = "float16" if torch.cuda.is_available() else "int8"
WHISPER_MODEL = WhisperModel("base", device="cuda" if torch.cuda.is_available() else "cpu", compute_type=compute_type)

DIARIZATION_PIPELINE = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    token=os.environ.get("HUGGING_FACE_ACCESS_TOKEN")
).to(device=device)

def convert_audio(state):
    try:
        # Use globally loaded models instead of reloading them
        model = WHISPER_MODEL
        diarization_pipeline = DIARIZATION_PIPELINE
        # 1. Grab the raw audio bytes from the State
        audio_bytes = state.get('cleaned_audio')
        
        if not audio_bytes:
            print("❌ Error: No audio bytes provided in state.")
            return {"converted_audio": "ERROR: No audio bytes found"}
        # 2. Write the bytes securely into a temporary file
        # We use a context manager to ensure it gets created properly
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
            temp_audio.write(audio_bytes)
            temp_path = temp_audio.name  # Get the path of the temporary file
        try:
            logging.info(f"✅ Loaded raw bytes into temporary file: {temp_path}")
            
            # 3. Now we can proceed exactly like your old logic, but pointing to `temp_path`
            duration = librosa.get_duration(path=temp_path)
            logging.info(f"⏱️ Audio duration: {duration:.2f} seconds")
            
            if duration < 10:
                logging.info("⚠️ Audio too short for diarization, using transcription only.")
                segments_gen, _ = model.transcribe(temp_path)
                segments = list(segments_gen)
                final_transcript = [f"UNKNOWN: {seg.text.strip()}" for seg in segments]
                return {"converted_audio": "\n".join(final_transcript)}
            
            logging.info("👥 Identifying speakers (this may take a few minutes)...")
            diarization = diarization_pipeline(temp_path)
            
            logging.info(f"🎤 Whisper is transcribing (this may take a few minutes)...")
            segments_gen, _ = model.transcribe(temp_path)
            segments = list(segments_gen)
            final_transcript = []
            
            for segment in segments:
                start_time = segment.start
                end_time = segment.end
                text = segment.text.strip()
                
                try:
                    intersection = diarization.crop(Segment(start_time, end_time))
                    active_speakers = intersection.labels()
                    
                    if active_speakers:
                        speaker = active_speakers[0] 
                    else:
                        speaker = "UNKNOWN"
                except Exception as e:
                    logging.error(f"Speaker detection error: {e}")
                    speaker = "UNKNOWN"
                    
                final_transcript.append(f"{speaker}: {text}")
            
            logging.info("✅ Transcription & Diarization Complete.")
            return {"converted_audio": "\n".join(final_transcript)}
        finally:
            # 4. CRITICAL: Clean up! Delete the temporary file so we don't leak storage 
            # This 'finally' block ensures deletion even if an error occurs above
            if os.path.exists(temp_path):
                os.remove(temp_path)
                print("🧹 Cleaned up temporary audio file.")
    
    except Exception as e:
        print(f"❌ Error in convert_audio: {str(e)}")
        traceback.print_exc()
        return {"converted_audio": f"ERROR: {str(e)}"}
    
def generate_summary(state):
    try:
        print("In summary")
        summary_prompt = getPrompts()[0]
        converted_text = state.get('converted_audio', '')
        if not converted_text:
            return {"key_decisions": "No audio content to analyze"}
        logging.info("Prompts received successfully")
        chain = summary_prompt | QWEN_MODEL | StrOutputParser()
        summary = chain.invoke({"converted_audio": converted_text})
        print(f"Summary: {summary}")
        return {"summary": summary}
    except Exception as e:
        raise CustomException(e, sys)
    
def generate_action_items(state):
    try:
        print("In action items")
        action_items_prompt = getPrompts()[1]
        action_items_parser = generate_structured_outputs()[0]
        converted_text = state.get('converted_audio', '')
        if not converted_text:
            return {"key_decisions": "No audio content to analyze"}
        chain = action_items_prompt | QWEN_MODEL | action_items_parser
        action_items_result = chain.invoke({"converted_audio": converted_text})
        # Extract the list of dictionaries from the Pydantic model
        action_items = [item.dict() for item in action_items_result.items]
        print(f"Action items: {action_items}")
        return {"action_items": action_items}
    except Exception as e:
        raise CustomException(e, sys)
    
def generate_key_decisions(state):
    try:
        print("In key decisions")
        key_decisions_prompt = getPrompts()[2]
        key_decisions_parser = generate_structured_outputs()[1]
        converted_text = state.get('converted_audio', '')
        if not converted_text:
            return {"key_decisions": "No audio content to analyze"}
        chain = key_decisions_prompt | QWEN_MODEL | key_decisions_parser
        key_decisions_result = chain.invoke({"converted_audio": converted_text})
        # Extract the list of dictionaries from the Pydantic model
        key_decisions = [item.dict() for item in key_decisions_result.items]
        print(f"Key decisions: {key_decisions}")
        return {"key_decisions": key_decisions}
    except Exception as e:
        raise CustomException(e, sys)

def evaluate_summary(state):
    try:
        print("In evaluation summary")
        evaluation_prompt = getPrompts()[5]
        converted_audio = state.get("converted_audio", "")
        current_summary = state.get("summary", "")
        evaluation_parser = generate_structured_outputs()[2]
        if not converted_audio:
            return {"key_decisions": "No audio content to analyze"}
        chain = evaluation_prompt | PHI_MODEL | evaluation_parser
        result = chain.invoke({
            "converted_audio": state['converted_audio'],
            "component_type": "Summary",
            "generated_content": current_summary
        })
        return {"summary_evaluation": result.evaluation, "summary_feedback": result.feedback}
    except Exception as e:
        raise CustomException(e, sys)
    
def evaluate_action_items(state):
    try:
        print("In action items summary")
        evaluation_prompt = getPrompts()[5]
        converted_audio = state.get("converted_audio", "")
        current_action_items = state.get("action_items", "")
        evaluation_parser = generate_structured_outputs()[2]
        if not converted_audio:
            return {"key_decisions": "No audio content to analyze"}
        chain = evaluation_prompt | PHI_MODEL | evaluation_parser
        result = chain.invoke({
            "converted_audio": state['converted_audio'],
            "component_type": "Action Items",
            "generated_content": current_action_items
        })
        return {"action_items_evaluation": result.evaluation, "action_items_feedback": result.feedback}
    except Exception as e:
        raise CustomException(e, sys)
    
def evaluate_key_decisions(state):
    try:
        print("In key decisions summary")
        evaluation_prompt = getPrompts()[5]
        converted_audio = state.get("converted_audio", "")
        current_key_decisions = state.get("key_decisions", "")
        evaluation_parser = generate_structured_outputs()[2]
        if not converted_audio:
            return {"key_decisions": "No audio content to analyze"}
        chain = evaluation_prompt | PHI_MODEL | evaluation_parser
        result = chain.invoke({
            "converted_audio": state['converted_audio'],
            "component_type": "Key Decisions",
            "generated_content": current_key_decisions
        })
        return {"key_decisions_evaluation": result.evaluation, "key_decisions_feedback": result.feedback}
    except Exception as e:
        raise CustomException(e, sys)
    
def format_text(state):
    """
        This node creates the final string that the user actually sees.
    """
    # 1. Get data from State
    summary_text = state.get("summary", "No summary available.")
    actions_list = state.get("action_items", [])
    decisions_list = state.get("key_decisions", [])

    # 2. Format Action Items 
    formatted_actions = ""
    # If it's a string, just use it. Otherwise, loop through the List of Dictionaries.
    if isinstance(actions_list, str):
        formatted_actions = actions_list
    elif actions_list and len(actions_list) > 0:
        for item in actions_list:
            formatted_actions += f"- **Action Item:** {item.get('action_item', 'N/A')} | **Speaker:** {item.get('speaker', 'Unknown')} | **Deadline:** {item.get('deadline', 'N/A')} | **Status:** {item.get('status', 'N/A')}\n"
    else:
        formatted_actions = "No action items identified."

    # 3. Format Key Decisions 
    formatted_decisions = ""
    if isinstance(decisions_list, str):
        formatted_decisions = decisions_list
    elif decisions_list and len(decisions_list) > 0:
        for item in decisions_list:
            formatted_decisions += f"- **Topic:** {item.get('topic', 'N/A')} | **Decision:** {item.get('decision', 'N/A')} | **Speaker:** {item.get('speaker', 'Unknown')}\n"
    else:
        formatted_decisions = "No key decisions recorded."

    # 4. Combine everything into the User View
    user_view = f"""
    =========================================
            MEETING ANALYSIS REPORT
    =========================================

    SUMMARY:
    {summary_text}

    -----------------------------------------
    ACTION ITEMS:
    {formatted_actions}

    -----------------------------------------
    KEY DECISIONS:
    {formatted_decisions}
    =========================================
    """
        
        # Save to the final state field (assuming you add 'final_report' to your TypedDict)
    return {"final_report": user_view}
        
def check_summary(state):
    try:
        evaluation = state.get('summary_evaluation', 'needs_improvement')
        if evaluation == "approved" or state.get('summary_iterations', 0) > state.get('max_iterations', 3):
            return "approved"
        return "needs_improvement"
    except Exception as e:
        raise CustomException(e, sys)

def check_action_items(state):
    try:
        evaluation = state.get('action_items_evaluation', 'needs_improvement')
        if evaluation == "approved" or state.get('action_items_iterations', 0) > state.get('max_iterations', 3):
            return "approved"
        return "needs_improvement"
    except Exception as e:
        raise CustomException(e, sys)

def check_key_decisions(state):
    try:
        evaluation = state.get('key_decisions_evaluation', 'needs_improvement')
        if evaluation == "approved" or state.get('key_decisions_iterations', 0) > state.get('max_iterations', 3):
            return "approved"
        return "needs_improvement"
    except Exception as e:
        raise CustomException(e, sys)

def optimize_summary(state):
    try:
        print("In summary optimization")
        summary_optimization_prompt = getPrompts()[6]
        chain = summary_optimization_prompt | QWEN_MODEL | StrOutputParser()
        summary = chain.invoke({
            "converted_audio": state['converted_audio'],
            "current_summary": state['summary'],
            "feedback": state['summary_feedback']
        })
        iteration = state['summary_iterations'] + 1
        return {"summary": summary, "summary_iterations": iteration}
    except Exception as e:
        raise CustomException(e, sys)
    
def optimize_action_items(state):
    try:
        print("In action items optimization")
        action_items_optimization_prompt = getPrompts()[7]
        parser = generate_structured_outputs()[0]
        chain = action_items_optimization_prompt | QWEN_MODEL | parser
        action_items_result = chain.invoke({
            "converted_audio": state['converted_audio'],
            "current_action_items": state['action_items'],
            "feedback": state['action_items_feedback']
        })
        action_items = [item.dict() for item in action_items_result.items]
        iteration = state['action_items_iterations'] + 1
        return {"action_items": action_items, "action_items_iterations": iteration}
    except Exception as e:
        raise CustomException(e, sys)
    
def optimize_key_decisions(state):
    try:
        print("In key decisions optimization")
        key_decisions_optimization_prompt = getPrompts()[8]
        parser = generate_structured_outputs()[1]
        chain = key_decisions_optimization_prompt | QWEN_MODEL | parser
        key_decisions_result = chain.invoke({
            "converted_audio": state['converted_audio'],
            "current_key_decisions": state['key_decisions'],
            "feedback": state['key_decisions_feedback']
        })
        key_decisions = [item.dict() for item in key_decisions_result.items]
        iteration = state['key_decisions_iterations'] + 1
        return {"key_decisions": key_decisions, "key_decisions_iterations": iteration}
    except Exception as e:
        raise CustomException(e, sys)