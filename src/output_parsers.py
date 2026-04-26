import sys

from langchain_classic.output_parsers import StructuredOutputParser, ResponseSchema, PydanticOutputParser
from src.exception import CustomException
from src.logger import logging
from pydantic import BaseModel
from typing import Literal, Annotated

def generate_structured_outputs():
    try:
        from pydantic import Field
        from typing import List

        class ActionItem(BaseModel):
            speaker: str = Field(description="The exact name of the speaker assigned to the action (e.g., SPEAKER_00). If it is a general team task, write 'Team'.")
            action_item: str = Field(description="A clear, concise description of the task or promise made.")
            deadline: str = Field(description="The deadline mentioned for the task. If no explicit deadline was mentioned, output 'Not Specified'.")
            status: Literal['High', 'Medium', 'Low'] = Field(description="The urgency of the action item.")

        class ActionItems(BaseModel):
            items: List[ActionItem] = Field(description="A list of all action items extracted from the transcript.")

        class KeyDecision(BaseModel):
            topic: str = Field(description="The main subject of the decision (e.g., Tech Stack, Budget).")
            decision: str = Field(description="A clear description of what was finally agreed upon.")
            speaker: str = Field(description="The exact ID of the speaker who made the final call (e.g., SPEAKER_02).")

        class KeyDecisions(BaseModel):
            items: List[KeyDecision] = Field(description="A list of all key decisions extracted from the transcript.")

        class Evaluation(BaseModel):
            evaluation: Literal["approved", "needs_improvement"]
            feedback: str

        action_items_parser = PydanticOutputParser(pydantic_object=ActionItems)
        key_decisions_parser = PydanticOutputParser(pydantic_object=KeyDecisions)
        evaluation_parser = PydanticOutputParser(pydantic_object=Evaluation)

        return action_items_parser, key_decisions_parser, evaluation_parser
    except Exception as e:
        raise CustomException(e, sys)