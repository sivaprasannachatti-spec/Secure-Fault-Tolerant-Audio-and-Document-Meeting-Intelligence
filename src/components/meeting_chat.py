import sys

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_ollama import ChatOllama
from src.exception import CustomException
from src.logger import logging
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
from src.utils import QWEN_MODEL

class MeetingChat:
    def handleNewMeetingChat(self, query, final_report):
        try:
            prompt = self.createPrompt()[0]
            llm = QWEN_MODEL
            chain = prompt | llm | StrOutputParser()
            result = chain.invoke({"final_report": final_report, "query": query})
            return result
        except Exception as e:
            raise CustomException(e, sys)

    def streamNewMeetingChat(self, query, final_report):
        try:
            prompt = self.createPrompt()[0]
            llm = QWEN_MODEL
            chain = prompt | llm | StrOutputParser()
            return chain.stream({"final_report": final_report, "query": query})
        except Exception as e:
            raise CustomException(e, sys)

    def handleOldMeetingChat(self, query, chat_history, final_report):
        try:
            prompt = self.createPrompt()[1]
            llm = QWEN_MODEL
            chain = prompt | llm | StrOutputParser()
            result = chain.invoke({"final_report": final_report, "chat_history": chat_history, "query": query})
            return result
        except Exception as e:
            raise CustomException(e, sys)

    def streamOldMeetingChat(self, query, chat_history, final_report):
        try:
            prompt = self.createPrompt()[1]
            llm = QWEN_MODEL
            chain = prompt | llm | StrOutputParser()
            return chain.stream({"final_report": final_report, "chat_history": chat_history, "query": query})
        except Exception as e:
            raise CustomException(e, sys)
    def createPrompt(self):
        try:
            new_meeting_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are an intelligent Meeting Assistant. You have access to a meeting's analysis report 
            that includes the summary, action items, and key decisions. Your job is to answer the user's 
            questions accurately based ONLY on the meeting content provided below.
            ### Rules:
            1) Answer strictly based on the meeting data provided. Do not make up or assume any information 
            that is not present in the report.
            2) If the user's question cannot be answered from the given meeting data, clearly say: 
            "This information is not available in the meeting report."
            3) When referring to speakers, use their Speaker IDs (e.g., SPEAKER_00, SPEAKER_01).
            4) Be concise, professional, and helpful in your responses.
            5) If the question is about action items, include the assignee, deadline, and urgency if available.
            6) If the question is about decisions, include who made the decision and the reasoning if available.
            ### Meeting Report:
            {final_report}
            """),
            ("human", "{query}")
            ])
            old_meeting_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are an intelligent Meeting Assistant continuing a conversation about a meeting. 
            You have access to the meeting's analysis report and the previous conversation history.
            ### Rules:
            1) Answer based on the meeting data AND the context from previous messages in this conversation.
            2) Do not contradict your previous answers unless correcting a mistake.
            3) If the user refers to something discussed earlier in the chat (e.g., "tell me more about that"), 
            use the chat history to understand what "that" refers to.
            4) Do not make up or assume any information not present in the meeting report.
            5) If the answer is not available, clearly say so.
            6) Be concise, professional, and helpful.
            ### Meeting Report:
            {final_report}
            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{query}")
            ])
            return(
                new_meeting_prompt,
                old_meeting_prompt,
            )
        except Exception as e:
            raise CustomException(e, sys)