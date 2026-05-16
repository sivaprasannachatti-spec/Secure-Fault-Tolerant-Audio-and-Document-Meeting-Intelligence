"""
Document Chat — Chat handler for document-based meetings.

Equivalent of meeting_chat.py but uses the Document Tree as context
instead of the audio final_report.
Uses the Document provider pool (Gemini -> Groq -> HuggingFace).
"""

import sys

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from src.exception import CustomException
from src.logger import logging
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser


def log_tree_context(query, document_tree):
    """Helper to explicitly log the exact document tree context being sent to the LLM."""
    tree_str = str(document_tree)
    logging.info(f"🔍 [LLM PRE-FLIGHT CHECK] Query: {query}")
    logging.info(f"🌳 [LLM TREE CONTEXT] Length: {len(tree_str)} chars")
    logging.info(f"🌳 [LLM TREE CONTEXT PREVIEW] {tree_str[:3000]}...")


class DocumentChat:
    """Handles AI chat interactions grounded in document tree context."""
    
    def handleNewDocumentChat(self, query, document_tree):
        """Invoke a new chat response using the document tree as context."""
        try:
            from src.providers.llm_service import invoke_document_chat
            prompt = self.createPrompt()[0]
            log_tree_context(query, document_tree)
            result = invoke_document_chat(
                chain_builder=lambda llm: prompt | llm | StrOutputParser(),
                invoke_args={"document_tree": document_tree, "query": query}
            )
            return result
        except Exception as e:
            raise CustomException(e, sys)

    def streamNewDocumentChat(self, query, document_tree):
        """Stream a new chat response token-by-token using document tree context."""
        try:
            from src.providers.llm_service import stream_document_chat
            prompt = self.createPrompt()[0]
            log_tree_context(query, document_tree)
            for chunk in stream_document_chat(
                chain_builder=lambda llm: prompt | llm | StrOutputParser(),
                invoke_args={"document_tree": document_tree, "query": query}
            ):
                text = chunk if isinstance(chunk, str) else getattr(chunk, 'content', str(chunk))
                yield text
        except Exception as e:
            raise CustomException(e, sys)

    def handleOldDocumentChat(self, query, chat_history, document_tree):
        """Invoke an old chat response with history and document tree context."""
        try:
            from src.providers.llm_service import invoke_document_chat
            prompt = self.createPrompt()[1]
            log_tree_context(query, document_tree)
            result = invoke_document_chat(
                chain_builder=lambda llm: prompt | llm | StrOutputParser(),
                invoke_args={"document_tree": document_tree, "chat_history": chat_history, "query": query}
            )
            return result
        except Exception as e:
            raise CustomException(e, sys)

    def streamOldDocumentChat(self, query, chat_history, document_tree):
        """Stream an old chat response with history and document tree context."""
        try:
            from src.providers.llm_service import stream_document_chat
            prompt = self.createPrompt()[1]
            log_tree_context(query, document_tree)
            for chunk in stream_document_chat(
                chain_builder=lambda llm: prompt | llm | StrOutputParser(),
                invoke_args={"document_tree": document_tree, "chat_history": chat_history, "query": query}
            ):
                text = chunk if isinstance(chunk, str) else getattr(chunk, 'content', str(chunk))
                yield text
        except Exception as e:
            raise CustomException(e, sys)

    def createPrompt(self):
        """Returns (new_doc_chat_prompt, old_doc_chat_prompt) from getDocumentPrompts()."""
        try:
            from src.prompts.prompts import getDocumentPrompts
            prompts = getDocumentPrompts()
            return (prompts[8], prompts[9])  # doc_chat_new_prompt, doc_chat_old_prompt
        except Exception as e:
            raise CustomException(e, sys)
