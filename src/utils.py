import os
import platform
# Python 3.14 Windows Hang Fix
if os.name == 'nt' and not hasattr(platform, '_monkeypatched'):
    platform.system = lambda: "Windows"
    platform.release = lambda: "10"
    platform.version = lambda: "10.0.19041"
    platform.python_version = lambda: "3.14.3"
    platform._monkeypatched = True

import sys
import os
import traceback

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field
from langchain_classic.output_parsers import StructuredOutputParser, ResponseSchema, PydanticOutputParser
from src.exception import CustomException
from src.logger import logging
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
LLAMA_MODEL = ChatOllama(model='llama3.2:3b', keep_alive=-1)
PHI_MODEL = ChatOllama(model='phi4-mini', keep_alive=-1)

# Pyannote and local Whisper have been removed to save RAM.
# AssemblyAI and Deepgram now handle transcription and diarization natively.

def convert_audio(state):
    try:
        # 1. Grab the raw audio bytes from the State
        audio_bytes = state.get('cleaned_audio')
        
        if not audio_bytes:
            print("❌ Error: No audio bytes provided in state.")
            return {"converted_audio": "ERROR: No audio bytes found"}
            
        logging.info("🎤 Sending audio to AssemblyAI/Deepgram orchestrator...")
        
        try:
            import asyncio
            from src.providers.asr_service import transcribe_audio_full
            
            # Run async transcription from sync context
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    final_transcript = pool.submit(asyncio.run, transcribe_audio_full(audio_bytes)).result()
            except RuntimeError:
                final_transcript = asyncio.run(transcribe_audio_full(audio_bytes))
                
        except Exception as e:
            logging.error(f"⚠️ ASR service failed: {e}")
            return {"converted_audio": f"ERROR: {str(e)}"}
            
        logging.info("✅ Transcription & Diarization Complete.")
        return {"converted_audio": final_transcript}
    
    except Exception as e:
        print(f"❌ Error in convert_audio: {str(e)}")
        traceback.print_exc()
        return {"converted_audio": f"ERROR: {str(e)}"}
    
def generate_summary(state):
    try:
        from src.providers.llm_service import invoke_generation
        summary_prompt = getPrompts()[0]
        converted_text = state.get('converted_audio', '')
        if not converted_text:
            return {"summary": "No audio content to analyze"}
        
        result = invoke_generation(
            chain_builder=lambda llm: summary_prompt | llm | StrOutputParser(),
            invoke_args={"converted_audio": converted_text}
        )
        return {"summary": result}
    except Exception as e:
        raise CustomException(e, sys)

def stream_summary(state):
    """Generator for streaming summary tokens."""
    try:
        from src.providers.llm_service import stream_generation
        summary_prompt = getPrompts()[0]
        converted_text = state.get('converted_audio', '')
        if not converted_text:
            yield False, "No audio content to analyze"
            return

        for is_thought, token in stream_generation(
            chain_builder=lambda llm: summary_prompt | llm | StrOutputParser(),
            invoke_args={"converted_audio": converted_text}
        ):
            yield is_thought, token

    except Exception as e:
        logging.error(f"Error in stream_summary: {e}")
        yield f"ERROR: {str(e)}"

    
def extract_json_array(text: str) -> list:
    """Greedy extraction of a JSON array from LLM output."""
    import json
    import re
    try:
        # Look for the first '[' and last ']'
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            clean_json = match.group(0)
            return json.loads(clean_json)
        return []
    except Exception as e:
        logging.error(f"Greedy JSON extraction failed: {e}")
        return []

def generate_meeting_title(state):
    """Generates a title quickly using the early transcript."""
    try:
        from src.providers.llm_service import invoke_generation
        title_prompt = getPrompts()[3]
        transcript = state.get('converted_audio', '')
        
        # Use only first ~2000 words for speed
        early_context = " ".join(transcript.split()[:2000])
        
        result = invoke_generation(
            chain_builder=lambda llm: title_prompt | llm | StrOutputParser(),
            invoke_args={"meeting_content": early_context}
        )
        # Clean title from any quotes or "Title:" prefix
        clean_title = result.replace('Title:', '').replace('"', '').strip()
        return {"title": clean_title}
    except Exception as e:
        logging.error(f"Title generation failed: {e}")
        return {"title": "Team Sync Meeting"}

def generate_action_items(state):
    try:
        from src.providers.llm_service import invoke_generation
        action_items_prompt = getPrompts()[1]
        converted_text = state.get('converted_audio', '')
        if not converted_text:
            return {"action_items": []}
        
        # We use StrOutputParser first to get the raw text, then handle the JSON ourselves for robustness
        raw_result = invoke_generation(
            chain_builder=lambda llm: action_items_prompt | llm | StrOutputParser(),
            invoke_args={"converted_audio": converted_text}
        )
        
        action_items = extract_json_array(raw_result)
        return {"action_items": action_items}
    except Exception as e:
        logging.error(f"Action item extraction failed: {e}")
        return {"action_items": []}

def generate_key_decisions(state):
    try:
        from src.providers.llm_service import invoke_generation
        key_decisions_prompt = getPrompts()[2]
        converted_text = state.get('converted_audio', '')
        if not converted_text:
            return {"key_decisions": []}
        
        raw_result = invoke_generation(
            chain_builder=lambda llm: key_decisions_prompt | llm | StrOutputParser(),
            invoke_args={"converted_audio": converted_text}
        )
        
        key_decisions = extract_json_array(raw_result)
        return {"key_decisions": key_decisions}
    except Exception as e:
        logging.error(f"Key decision extraction failed: {e}")
        return {"key_decisions": []}

def stream_key_decisions(state):
    """Generator for streaming key decisions tokens (raw JSON)."""
    try:
        from src.providers.llm_service import stream_generation
        key_decisions_prompt = getPrompts()[2]
        converted_text = state.get('converted_audio', '')
        if not converted_text:
            yield False, "[]"
            return


        for is_thought, token in stream_generation(
            chain_builder=lambda llm: key_decisions_prompt | llm | StrOutputParser(),
            invoke_args={"converted_audio": converted_text},
            task_type="key_decisions"
        ):

            yield is_thought, token

    except Exception as e:
        logging.error(f"Error in stream_key_decisions: {e}")
        yield False, f"ERROR: {str(e)}"


async def astream_summary(state):
    """Async generator for streaming summary tokens."""
    try:
        from src.providers.llm_service import astream_generation
        summary_prompt = getPrompts()[0]
        converted_text = state.get('converted_audio', '')
        if not converted_text:
            yield False, "No audio content to analyze"
            return


        async for is_thought, token in astream_generation(
            chain_builder=lambda llm: summary_prompt | llm | StrOutputParser(),
            invoke_args={"converted_audio": converted_text},
            task_type="summary"
        ):

            yield is_thought, token

    except Exception as e:
        logging.error(f"Error in astream_summary: {e}")
        yield False, f"ERROR: {str(e)}"


async def astream_action_items(state):
    """Async generator for streaming action items tokens."""
    try:
        from src.providers.llm_service import astream_generation
        action_items_prompt = getPrompts()[1]
        converted_text = state.get('converted_audio', '')
        if not converted_text:
            yield False, "[]"
            return


        async for is_thought, token in astream_generation(
            chain_builder=lambda llm: action_items_prompt | llm | StrOutputParser(),
            invoke_args={"converted_audio": converted_text},
            task_type="action_items"
        ):

            yield is_thought, token

    except Exception as e:
        logging.error(f"Error in astream_action_items: {e}")
        yield False, f"ERROR: {str(e)}"


async def astream_key_decisions(state):
    """Async generator for streaming key decisions tokens."""
    try:
        from src.providers.llm_service import astream_generation
        key_decisions_prompt = getPrompts()[2]
        converted_text = state.get('converted_audio', '')
        if not converted_text:
            yield False, "[]"
            return


        async for is_thought, token in astream_generation(
            chain_builder=lambda llm: key_decisions_prompt | llm | StrOutputParser(),
            invoke_args={"converted_audio": converted_text},
            task_type="key_decisions"
        ):

            yield is_thought, token

    except Exception as e:
        logging.error(f"Error in astream_key_decisions: {e}")
        yield False, f"ERROR: {str(e)}"




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
        This node creates the final structured JSON report.
    """
    import json
    
    # 1. Get data from State
    summary_text = state.get("summary", "No summary available.")
    actions_list = state.get("action_items", [])
    decisions_list = state.get("key_decisions", [])

    # 2. Normalize action items
    if isinstance(actions_list, str):
        actions_list = [{"action_item": actions_list, "speaker": "Unknown", "deadline": "N/A", "status": "N/A"}]
    elif not actions_list:
        actions_list = []

    # 3. Normalize key decisions
    if isinstance(decisions_list, str):
        decisions_list = [{"topic": "General", "decision": decisions_list, "speaker": "Unknown"}]
    elif not decisions_list:
        decisions_list = []

    # 4. Build structured report as JSON string
    report = {
        "summary": summary_text,
        "action_items": actions_list,
        "key_decisions": decisions_list
    }
        
    return {"final_report": json.dumps(report)}
        
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