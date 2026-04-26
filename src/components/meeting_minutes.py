import sys

from fastapi import HTTPException
from langgraph.graph import StateGraph, START, END
from src.exception import CustomException
from src.logger import logging
from src.utils import convert_audio, generate_summary, generate_action_items, generate_key_decisions, format_text, evaluate_summary, evaluate_action_items, evaluate_key_decisions, check_summary, check_action_items, check_key_decisions, optimize_summary, optimize_action_items, optimize_key_decisions
from src.meeting_state import MeetingMinutes as MeetingMinutes

class MeetingProcessor:
    def generateMeetingMinutes(self, target_dept, cleaned_audio):
        try:
            if cleaned_audio == None:
                raise HTTPException(status_code=404, detail="Please upload any meeting")
            ## building the graph
            graph = StateGraph(state_schema=MeetingMinutes)
            ## define the nodes
            graph.add_node("convert_audio", convert_audio)
            graph.add_node("generate_summary", generate_summary)
            graph.add_node("generate_action_items", generate_action_items)
            graph.add_node("generate_key_decisions", generate_key_decisions)
            graph.add_node("evaluate_summary", evaluate_summary)
            graph.add_node("optimize_summary", optimize_summary)
            graph.add_node("evaluate_action_items", evaluate_action_items)
            graph.add_node("optimize_action_items", optimize_action_items)
            graph.add_node("evaluate_key_decisions", evaluate_key_decisions)
            graph.add_node("optimize_key_decisions", optimize_key_decisions)
            graph.add_node("format_text", format_text)
            ## define the edges
            ## define the edges
            graph.add_edge(START, "convert_audio")
            
            # Fan-out: Start all three generations in parallel after audio conversion
            graph.add_edge("convert_audio", "generate_summary")
            graph.add_edge("convert_audio", "generate_action_items")
            graph.add_edge("convert_audio", "generate_key_decisions")

            # Independent Refinement Loops for each component
            # graph.add_edge("generate_summary", "evaluate_summary")
            # graph.add_conditional_edges("evaluate_summary", check_summary, {"approved": "format_text", "needs_improvement": "optimize_summary"})
            # graph.add_edge("optimize_summary", "evaluate_summary")

            # graph.add_edge("generate_action_items", "evaluate_action_items")
            # graph.add_conditional_edges("evaluate_action_items", check_action_items, {"approved": "format_text", "needs_improvement": "optimize_action_items"})
            # graph.add_edge("optimize_action_items", "evaluate_action_items")

            # graph.add_edge("generate_key_decisions", "evaluate_key_decisions")
            # graph.add_conditional_edges("evaluate_key_decisions", check_key_decisions, {"approved": "format_text", "needs_improvement": "optimize_key_decisions"})
            # graph.add_edge("optimize_key_decisions", "evaluate_key_decisions")

            # # Convergence: All paths wait for each other at format_text
            # graph.add_edge("format_text", END)
            graph.add_edge("generate_summary", "format_text")
            graph.add_edge("generate_action_items", "format_text")
            graph.add_edge("generate_key_decisions", "format_text")
            graph.add_edge("format_text", END)
            workflow = graph.compile()
                
            initial_state_with_audio = {
                "cleaned_audio": cleaned_audio,
                # "max_iterations": 1,
                # "summary_iterations": 0,
                # "action_items_iterations": 0,
                # "key_decisions_iterations": 0
            }
            
            result = workflow.invoke(initial_state_with_audio)
            final_report = result.get('final_report', '')
            return final_report
        except Exception as e:
            raise CustomException(e, sys)
