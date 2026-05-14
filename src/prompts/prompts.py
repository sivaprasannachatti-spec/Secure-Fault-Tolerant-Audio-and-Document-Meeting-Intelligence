import sys

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from src.exception import CustomException
from src.logger import logging
from src.output_parsers import generate_structured_outputs
from langchain_core.prompts import ChatPromptTemplate

def getPrompts():
     try:
          action_items_parser, key_decisions_parser, evaluation_parser = generate_structured_outputs()
          summary_prompt = ChatPromptTemplate.from_messages([
               ("system", """
          You are a Senior AI Meeting Assistant.
          Your objective is to generate a highly concise, speaker-aware, executive-style summary.
          
          ### RULES:
          1. **Executive Overview:** Start with a single, high-quality paragraph (3-4 sentences) that provides context on what the meeting is about, its primary goal, and the overarching conclusion.
          2. **Speaker-Aware Bullets:** Below the overview, group specific points by speaker using the exact tags (e.g., SPEAKER_00).
          3. **Format:** 
             SPEAKER_XX:
             * Concise point about discussion.
             * Technical/Business impact mentioned.
          4. **Spacing:** ALWAYS add two newlines (\n\n) between the overview and the first speaker, and between subsequent speaker sections.
          5. **High-Value Only:** Focus on technical discussions, business impacts, and blockers. Ignore small talk.
          6. **Markdown Only:** Use standard markdown formatting.


          """),

          ("human", """
          Transcript:
          {converted_audio}
          
          Generate the concise speaker-aware summary:
          """)
          ])

          action_items_prompt = ChatPromptTemplate.from_messages([
          ("system", """
          You are a Senior AI Project Manager.
          Extract explicit action items, tasks, and commitments.
          
          ### RULES:
          1. **Speaker-Aware:** Clearly state who is responsible (e.g., SPEAKER_01).
          2. **Actionable:** Use verbs (e.g., "SPEAKER_01: Deploy the API update").
          3. **Concise:** One bullet per task.
          4. **JSON ONLY:** Output ONLY the raw JSON list. NO preamble (e.g. "Here are..."). NO formatting text.
          5. **Empty State:** If NO action items are identified, you MUST output exactly: []

          
          {format_instructions}
          """),
          ("human", """
          Transcript:
          {converted_audio}
          """)
          ]).partial(format_instructions=action_items_parser.get_format_instructions())

               
          key_decisions_prompt = ChatPromptTemplate.from_messages([
          ("system", """
          You are a Senior AI Meeting Strategist.
          Extract finalized key decisions and consensus points.
          
          ### RULES:
          1. **Speaker-Aware:** Identify who made or finalized the decision (e.g., SPEAKER_02).
          2. **Concise:** Focus on the outcome, not the debate.
          3. **JSON ONLY:** Output ONLY the raw JSON list. NO preamble. NO formatting text.
          4. **Empty State:** If NO key decisions are recorded, you MUST output exactly: []

          
          {format_instructions}
          """),
          ("human", """
          Transcript:
          {converted_audio}
          """)
          ]).partial(format_instructions=key_decisions_parser.get_format_instructions())


          meeting_title_prompt = ChatPromptTemplate.from_messages([
               ("system", """You are a professional title generator for meeting reports. Your task is to 
          analyze the provided meeting report and generate a clear, concise, and descriptive title.
          ### Rules:
          1) Read the entire report carefully including the summary, action items, and key decisions.
          2) Identify the core topic or purpose of the meeting.
          3) The title must be between 3 to 8 words only.
          4) The title should immediately tell a reader what the meeting was about.
          5) Do not use generic titles like "Meeting Summary" or "Team Discussion".
          6) Use specific keywords from the actual meeting content.
          7) Do not include dates, timestamps, or speaker IDs in the title.
          8) Return ONLY the title — no quotes, no explanation, no extra text.
          ### Examples of good titles:
          - Q3 Product Roadmap Planning
          - Backend Migration to AWS
          - New Hiring Process Review
          - Budget Approval for Marketing Campaign
          - Sprint 5 Feature Prioritization
          ### Examples of bad titles:
          - Meeting Summary (too generic)
          - Discussion About Various Topics (vague)
          - SPEAKER_01 and SPEAKER_02 Talk (includes speaker IDs)
          - Meeting on 15th March 2026 (includes date)
          ### Meeting Report:
          {final_report}
          """),
               ("human", "Generate a title for this meeting report.")
          ])

          chat_title_prompt = ChatPromptTemplate.from_messages([
               ("system", """
               You are an expert conversational categorizer. 
               Your sole task is to read a user's opening message and generate a highly concise, professional title for the chat session.

               ### CRITICAL RULES:
               1. The title MUST be between 2 to 5 words maximum.
               2. Do NOT answer the user's question or provide any explanations whatsoever.
               3. Capitalize the title as a formal header (e.g., "Assigned Action Items").
               4. Do not use generic filler words like "Question About", "Chat Regarding", or "User Inquiry".
               5. You must output ONLY the exact generated title text. Do NOT include quotation marks, periods, or any conversational filler.
               
               ### Examples:
               User: "Who was assigned to the marketing redesign?"
               Title: Marketing Redesign Assignment
               
               User: "What was the final decision on the Q3 budget?"
               Title: Q3 Budget Decision
               """),
               ("human", """
               Generate a chat title for this opening message:

               {user_prompt}
               """)
          ])


          evaluation_prompt = ChatPromptTemplate.from_messages([
          ("system", """
          You are a ruthless, highly critical AI Quality Assurance Lead.
          Your sole objective is to meticulously cross-reference an original diarized meeting transcript against a newly generated AI output (the {component_type}).
          You must look for any excuse to fail the output. Approve it ONLY if it is completely flawless.
          **Strict Rejection Criteria — Fail the output if:**
          1. **Hallucination:** It contains numbers, names, deadlines, or topics that do not exist in the original transcript.
          2. **Misattribution:** It assigns an idea, task, or decision to the wrong speaker.
          3. **Critical Omission:** It completely ignores a major phase, argument, or final decision clearly present in the text.
          4. **Poor Formatting:** It includes conversational filler text ("Here are the action items:"), conversational dialogue, or fails to be professional.
          You must choose either `approved` (if absolutely flawless) or `needs_improvement` (if a single error exists).
          If it `needs_improvement`, your feedback MUST be highly specific, directly pointing out exactly what was hallucinated, missed, or misattributed so that a secondary AI can correctly optimize it.
          **Critical JSON Formatting Rules:**
          1. Your response MUST be valid JSON.
          2. YOU MUST NOT wrap your response in a "properties" key.
          3. Return only the root-level keys: `evaluation` and `feedback`.
          4. No conversational filler or introductory text.
          
          {format_instructions}
          """),
          ("human", """
          **Original Diarized Transcript (The Ground Truth):**
          {converted_audio}
          =========================================
          **Generated {component_type} to Evaluate:**
          {generated_content}
          """)
          ]).partial(format_instructions=evaluation_parser.get_format_instructions())
          
          summary_optimization_prompt = ChatPromptTemplate.from_messages([
          ("system", """
          You are an advanced AI Meeting Assistant specializing in quality correction.
          A previously generated meeting summary has failed Quality Assurance checks. Your objective is to read the original transcript, review the drafted summary, and carefully apply the QA Feedback to rewrite and fix the summary.
          **You must strictly adhere to the following rules while rewriting:**
          1. **Executive Overview:** Start with a single, high-quality paragraph (3-4 sentences) providing the meeting's context and goal.
          2. **Speaker-Aware Bullets:** Below the overview, group specific points by speaker identifier (e.g., SPEAKER_00).
          3. **Accurate Attribution:** Retain the exact speaker identifiers. Do not hallucinate names.
          4. **Professional Tone:** Fix the issues from the QA feedback while maintaining a clean, structured layout.
          Do not include any conversational filler. Output ONLY the final, optimized summary.

          """),
          ("human", """
          **1. Original Diarized Transcript (Ground Truth):**
          {converted_audio}
          =========================================
          **2. Drafted Summary (Failed QA):**
          {current_summary}
          =========================================
          **3. QA Feedback (The issues you MUST fix):**
          {feedback}
          Please provide the fully corrected and optimized narrative summary below:
          """)
          ])

          action_items_optimization_prompt = ChatPromptTemplate.from_messages([
          ("system", """
          You are a meticulous AI Project Manager specializing in quality correction.
          A previously generated list of Action Items has failed Quality Assurance checks. Your objective is to read the original transcript, review the drafted action items, and carefully apply the QA Feedback to rewrite and fix the action items array.
          **You must strictly adhere to the following rules while rewriting:**
          1. Only extract actual tasks or commitments. Do not include general suggestions.
          2. For the 'speaker', use the exact speaker tags in the transcript (e.g., SPEAKER_01) who took ownership of the task. Do not hallucinate names.
          3. Keep the 'action_item' description highly actionable.
          4. Do not hallucinate deadlines. If none were discussed, note it as "Not Specified".
          5. Infer the 'status' (High, Medium, Low) based on the context of the conversation.
          **Critical Instruction:** Fix the explicit errors pointed out in the QA Feedback based ONLY on the original transcript. 
          You must strictly output your revised response according to the JSON format instructions provided below. Do not include any extra conversational text.
          {format_instructions}
          """),
          ("human", """
          **1. Original Diarized Transcript (Ground Truth):**
          {converted_audio}
          =========================================
          **2. Drafted Action Items (Failed QA):**
          {current_action_items}
          =========================================
          **3. QA Feedback (The issues you MUST fix):**
          {feedback}
          Please provide the fully corrected json output below:
          """)
          ]).partial(format_instructions=action_items_parser.get_format_instructions())
          
          key_decisions_optimization_prompt = ChatPromptTemplate.from_messages([
          ("system", """
          You are a highly analytical AI Meeting Strategist specializing in quality correction.
          A previously generated list of Key Decisions has failed Quality Assurance checks. Your objective is to read the original transcript, review the drafted key decisions, and carefully apply the QA Feedback to rewrite and fix the decisions array.
          **You must strictly adhere to the following rules while rewriting:**
          1. Only extract an item if there is a clear consensus, agreement, or a final call made. Do not extract ongoing debates or dropped ideas.
          2. Group the outcome under a concise, professional 'topic' (e.g., 'Release Timeline').
          3. For the 'speaker', identify the specific individual (e.g., SPEAKER_02) who proposed the winning idea or gave the final confirmation. 
          4. Do not hallucinate decisions. Base all corrections explicitly on the transcript text.
          **Critical Instruction:** Fix the exact errors pointed out in the QA Feedback without introducing any new facts. 
          You must strictly output your revised response according to the JSON format instructions provided below. Do not include any conversational filler text.
          {format_instructions}
          """),
          ("human", """
          **1. Original Diarized Transcript (Ground Truth):**
          {converted_audio}
          =========================================
          **2. Drafted Key Decisions (Failed QA):**
          {current_key_decisions}
          =========================================
          **3. QA Feedback (The issues you MUST fix):**
          {feedback}
          Please provide the fully corrected json output below:
          """)
          ]).partial(format_instructions=key_decisions_parser.get_format_instructions())

          return (
               summary_prompt, 
               action_items_prompt, 
               key_decisions_prompt,
               meeting_title_prompt,
               chat_title_prompt,
               evaluation_prompt,
               summary_optimization_prompt,
               action_items_optimization_prompt,
               key_decisions_optimization_prompt
               )

     except Exception as e:
          raise CustomException(e, sys)