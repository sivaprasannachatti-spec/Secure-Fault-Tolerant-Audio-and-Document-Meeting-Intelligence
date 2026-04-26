from typing import TypedDict, Annotated, List, Dict, Literal
from pydantic import BaseModel, Field

class MeetingMinutes(TypedDict):
    cleaned_audio: bytes
    converted_audio: str
    summary: str
    # summary_evaluation: Literal["approved", "needs_improvement"]
    # summary_feedback: str
    action_items: List[Dict[str, any]]
    # action_items_evaluation: Literal["approved", "needs_improvement"]
    # action_items_feedback: str
    key_decisions: List[Dict[str, any]]
    # key_decisions_evaluation: Literal["approved", "needs_improvement"]
    # key_decisions_feedback: str
    # summary_iterations: int
    # action_items_iterations: int
    # key_decisions_iterations: int
    final_report: str
    # max_iterations: int

state = MeetingMinutes()