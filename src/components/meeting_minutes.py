import sys

from fastapi import HTTPException
from langgraph.graph import StateGraph, START, END
from src.exception import CustomException
from src.logger import logging
from src.utils import convert_audio, generate_summary, generate_action_items, generate_key_decisions, format_text, evaluate_summary, evaluate_action_items, evaluate_key_decisions, check_summary, check_action_items, check_key_decisions, optimize_summary, optimize_action_items, optimize_key_decisions
from src.meeting_state import MeetingMinutes as MeetingMinutes

class MeetingProcessor:
    def streamMeetingMinutes(self, target_dept, cleaned_audio):
        """
        Generator that executes the meeting pipeline with PARALLEL real-time streaming.
        Restores the original parallel workflow while maintaining ChatGPT-style updates.
        """
        import json
        import queue
        from concurrent.futures import ThreadPoolExecutor

        if cleaned_audio is None:
            raise HTTPException(status_code=404, detail="Please upload any meeting")
        
        state = {"cleaned_audio": cleaned_audio}

        # Stage 1: Audio Transcription (Must be first)
        yield f"data: {json.dumps({'stage': 'transcription', 'status': 'in_progress'})}\n\n"
        result = convert_audio(state)
        state.update(result)
        yield f"data: {json.dumps({'stage': 'transcription', 'status': 'done'})}\n\n"

        # Prepare for Parallel Streaming
        token_queue = queue.Queue()
        # Add 'title' to the stages
        stages = ['title', 'summary', 'action_items', 'key_decisions']
        for stage in stages:
            yield f"data: {json.dumps({'stage': stage, 'status': 'in_progress'})}\n\n"

        def capture_result(generate_func, stage_name):
            try:
                result_dict = generate_func(state)
                # The result is a dict with the stage name as key
                val = result_dict.get(stage_name, "")
                state[stage_name] = val
                token_queue.put({'stage': stage_name, 'status': 'done', 'final_text': val})
            except Exception as e:
                import traceback
                logging.error(f"Error in {stage_name} generation: {e}\n{traceback.format_exc()}")
                token_queue.put({'stage': stage_name, 'status': 'error', 'error': str(e)})

        # Launch all 4 generations in parallel (Added Title)
        from src.utils import generate_meeting_title
        import time
        with ThreadPoolExecutor(max_workers=4) as executor:
            executor.submit(capture_result, generate_meeting_title, 'title')
            executor.submit(capture_result, generate_summary, 'summary')
            executor.submit(capture_result, generate_action_items, 'action_items')
            executor.submit(capture_result, generate_key_decisions, 'key_decisions')

            completed_stages = 0
            while completed_stages < 4:
                try:
                    item = token_queue.get(timeout=120) 
                    if item.get('status') in ['done', 'error']:
                        completed_stages += 1
                        # Forward the final status event to frontend
                        yield f"data: {json.dumps(item)}\n\n"
                except queue.Empty:
                    break

        # Stage 5: Format Final Report
        yield f"data: {json.dumps({'stage': 'formatting', 'status': 'in_progress'})}\n\n"
        result = format_text(state)
        state.update(result)
        
        final_report = state.get('final_report', '')
        yield f"data: {json.dumps({'stage': 'complete', 'final_report': final_report})}\n\n"



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
