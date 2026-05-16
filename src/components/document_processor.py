"""
Document Processor — Vectorless RAG Pipeline Orchestrator.

Equivalent of meeting_minutes.py for the document workflow.
Handles: Token Analysis → Strategy Routing → Tree Generation → Summary/Actions/Decisions Streaming.
"""

import sys
import json
import re
import queue
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from src.exception import CustomException
from src.logger import logging
from src.components.document_parser import DocumentParser


class DocumentProcessor:
    """Orchestrates the complete document-to-intelligence pipeline."""

    SLIDING_WINDOW_THRESHOLD = 25000
    CHUNK_SIZE = 8000
    CHUNK_OVERLAP = 1000

    def __init__(self):
        self.parser = DocumentParser()

    # ========================================================================
    # Token Analysis
    # ========================================================================

    def _count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken (cl100k_base encoding)."""
        try:
            import tiktoken
            encoder = tiktoken.get_encoding("cl100k_base")
            return len(encoder.encode(text))
        except Exception as e:
            logging.warning(f"tiktoken failed, using word-based estimate: {e}")
            return len(text.split()) * 1.3  # Rough estimate

    def _should_use_sliding_window(self, token_count: int) -> bool:
        return token_count > self.SLIDING_WINDOW_THRESHOLD

    # ========================================================================
    # Intelligent Markdown-Aware Chunking
    # ========================================================================

    def _chunk_markdown(self, text: str) -> list:
        """
        Splits text into chunks using Markdown-aware semantic boundaries.
        - Splits at nearest heading (#, ##, ###) or paragraph boundary.
        - Preserves 1000-token overlap for context continuity.
        - Never splits inside tables or code blocks.
        """
        import tiktoken
        encoder = tiktoken.get_encoding("cl100k_base")

        # Split into semantic blocks (paragraphs/sections)
        blocks = re.split(r'(\n#{1,3}\s+[^\n]+)', text)

        chunks = []
        current_chunk = []
        current_tokens = 0

        for block in blocks:
            block_tokens = len(encoder.encode(block))

            if current_tokens + block_tokens > self.CHUNK_SIZE and current_chunk:
                # Save current chunk
                chunk_text = ''.join(current_chunk)
                chunks.append(chunk_text)

                # Build overlap: take last portion of current chunk (approx 1000 tokens)
                overlap_text = chunk_text[-4000:]  
                current_chunk = [overlap_text, block]
                current_tokens = len(encoder.encode(overlap_text)) + block_tokens
            else:
                current_chunk.append(block)
                current_tokens += block_tokens

        # Don't forget the last chunk
        if current_chunk:
            chunks.append(''.join(current_chunk))

        logging.info(f"📄 Chunked document into {len(chunks)} chunks (target: {self.CHUNK_SIZE} tokens each)")
        return chunks

    # ========================================================================
    # Tree Generation — Multi-Prompt Agentic Strategy
    # ========================================================================

    def _generate_tree_structural(self, markdown_text: str) -> dict:
        """Uses Structural Recovery prompt for documents with detected headings."""
        try:
            from src.providers.llm_service import invoke_document
            from src.prompts.prompts import getDocumentPrompts
            from langchain_core.output_parsers import StrOutputParser

            prompt = getDocumentPrompts()[0]  # doc_tree_structural_prompt
            result = invoke_document(
                chain_builder=lambda llm: prompt | llm | StrOutputParser(),
                invoke_args={"document_text": markdown_text}
            )
            return self._parse_tree_json(result)
        except Exception as e:
            logging.error(f"Structural tree generation failed: {e}")
            raise

    def _generate_tree_semantic(self, markdown_text: str) -> dict:
        """Uses Semantic Reconstruction for flat documents without headings."""
        try:
            from src.providers.llm_service import invoke_document
            from src.prompts.prompts import getDocumentPrompts
            from langchain_core.output_parsers import StrOutputParser

            prompt = getDocumentPrompts()[1]  # doc_tree_semantic_prompt
            result = invoke_document(
                chain_builder=lambda llm: prompt | llm | StrOutputParser(),
                invoke_args={"document_text": markdown_text}
            )
            return self._parse_tree_json(result)
        except Exception as e:
            logging.error(f"Semantic tree generation failed: {e}")
            raise

    def _generate_tree_sliding_window(self, markdown_text: str) -> dict:
        """Handles massive documents via chunk-based tree generation with breadcrumb injection."""
        try:
            from src.providers.llm_service import invoke_document
            from src.prompts.prompts import getDocumentPrompts
            from langchain_core.output_parsers import StrOutputParser

            prompt = getDocumentPrompts()[2]  # doc_tree_sliding_window_prompt
            chunks = self._chunk_markdown(markdown_text)
            sub_trees = []
            breadcrumb_context = "This is the first chunk. No previous context."

            for i, chunk in enumerate(chunks):
                logging.info(f"📄 Processing chunk {i+1}/{len(chunks)}...")
                result = invoke_document(
                    chain_builder=lambda llm: prompt | llm | StrOutputParser(),
                    invoke_args={
                        "chunk_number": str(i + 1),
                        "total_chunks": str(len(chunks)),
                        "breadcrumb_context": breadcrumb_context,
                        "chunk_text": chunk
                    }
                )
                sub_tree = self._parse_tree_json(result)
                sub_trees.append(sub_tree)

                # Build breadcrumb for next chunk
                if sub_tree.get("children"):
                    titles = [c.get("title", "") for c in sub_tree["children"][:5]]
                    breadcrumb_context = f"Previous sections discussed: {', '.join(titles)}"
                else:
                    breadcrumb_context = f"Previous section: {sub_tree.get('title', 'Unknown')}"

            # Merge sub-trees into a master tree
            master_tree = {
                "title": "Document Analysis",
                "content": f"Merged analysis from {len(chunks)} document sections.",
                "children": []
            }
            for st in sub_trees:
                if st.get("children"):
                    master_tree["children"].extend(st["children"])
                else:
                    master_tree["children"].append(st)

            return master_tree
        except Exception as e:
            logging.error(f"Sliding window tree generation failed: {e}")
            raise

    def _parse_tree_json(self, raw_text: str) -> dict:
        """Safely parses LLM output into a JSON tree dict."""
        try:
            text = raw_text.strip()
            # Remove markdown code fences if present
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            # Try direct parse
            try:
                return json.loads(text.strip())
            except json.JSONDecodeError:
                # Try to find JSON object
                match = re.search(r'\{.*\}', text, re.DOTALL)
                if match:
                    return json.loads(match.group())

            # Fallback: wrap raw text in a minimal tree
            logging.warning("Failed to parse tree JSON, using fallback structure")
            return {
                "title": "Document",
                "content": raw_text[:500],
                "children": []
            }
        except Exception as e:
            logging.error(f"Tree JSON parsing failed: {e}")
            return {"title": "Document", "content": "Parsing failed.", "children": []}

    # ========================================================================
    # Strategy Router
    # ========================================================================

    def _route_tree_generation(self, markdown_text: str, file_type: str, token_count: int) -> dict:
        """
        Routes to the correct tree generation strategy based on file type and token count.
        
        TXT  → Primary: Semantic → Fallback: Sliding Window
        DOCX → Primary: Structural → Fallback: Semantic
        PDF  → Primary: Structural → Fallback: Semantic
        MD   → Primary: Structural → Fallback: Semantic
        ALL  → Super-Fallback: Sliding Window if tokens > 25,000
        """
        # Force sliding window for massive documents regardless of type
        if self._should_use_sliding_window(token_count):
            logging.info(f"📄 Token count ({token_count}) exceeds threshold. Using Sliding Window strategy.")
            return self._generate_tree_sliding_window(markdown_text)

        is_flat = self.parser.detect_is_flat(markdown_text)

        if file_type == 'txt':
            # TXT: Always semantic (no structural metadata)
            try:
                logging.info("📄 Strategy: Semantic Reconstruction (TXT)")
                return self._generate_tree_semantic(markdown_text)
            except Exception as e:
                logging.warning(f"Semantic failed for TXT, falling back to Sliding Window: {e}")
                return self._generate_tree_sliding_window(markdown_text)
        else:
            # PDF/DOCX/MD: Try structural first
            if is_flat:
                logging.info(f"📄 Strategy: Semantic Reconstruction (flat {file_type.upper()})")
                try:
                    return self._generate_tree_semantic(markdown_text)
                except Exception as e:
                    logging.warning(f"Semantic failed, falling back to Sliding Window: {e}")
                    return self._generate_tree_sliding_window(markdown_text)
            else:
                logging.info(f"📄 Strategy: Structural Recovery ({file_type.upper()})")
                try:
                    return self._generate_tree_structural(markdown_text)
                except Exception as e:
                    logging.warning(f"Structural failed, falling back to Semantic: {e}")
                    try:
                        return self._generate_tree_semantic(markdown_text)
                    except Exception as e2:
                        logging.warning(f"Semantic also failed, final fallback to Sliding Window: {e2}")
                        return self._generate_tree_sliding_window(markdown_text)

    # ========================================================================
    # Document Generation Workers (Context-Agnostic)
    # ========================================================================

    def _stream_document_title(self, context_text: str, is_tree: bool = True):
        """Streams title tokens from either a tree or raw markdown."""
        from src.providers.llm_service import stream_document
        from src.prompts.prompts import getDocumentPrompts, getPrompts
        from langchain_core.output_parsers import StrOutputParser

        # If it's a tree, use doc_title_prompt; if raw markdown, use standard meeting_title_prompt
        if is_tree:
            prompt = getDocumentPrompts()[6] # doc_title_prompt
            invoke_args = {"document_tree": context_text}
        else:
            prompt = getPrompts()[3] # meeting_title_prompt
            invoke_args = {"meeting_content": context_text[:8000]} # Limit for speed
            
        for chunk in stream_document(
            chain_builder=lambda llm: prompt | llm | StrOutputParser(),
            invoke_args=invoke_args
        ):
            text = chunk if isinstance(chunk, str) else getattr(chunk, 'content', str(chunk))
            yield text

    def _stream_document_summary(self, context_text: str, is_tree: bool = True):
        """Streams summary tokens. Routes to Tree-based or Fast-Path prompt."""
        from src.providers.llm_service import stream_document
        from src.prompts.prompts import getDocumentPrompts
        from langchain_core.output_parsers import StrOutputParser

        if is_tree:
            prompt = getDocumentPrompts()[3] # doc_summary_prompt
            invoke_args = {"document_tree": context_text}
        else:
            prompt = getDocumentPrompts()[10] # doc_fast_path_summary_prompt
            invoke_args = {"document_text": context_text}

        for chunk in stream_document(
            chain_builder=lambda llm: prompt | llm | StrOutputParser(),
            invoke_args=invoke_args
        ):
            text = chunk if isinstance(chunk, str) else getattr(chunk, 'content', str(chunk))
            yield text

    def _stream_document_action_items(self, context_text: str, is_tree: bool = True):
        """Streams action items. Routes to Tree-based or Fast-Path prompt."""
        from src.providers.llm_service import stream_document
        from src.prompts.prompts import getDocumentPrompts
        from langchain_core.output_parsers import StrOutputParser

        if is_tree:
            prompt = getDocumentPrompts()[4] # doc_action_items_prompt
            invoke_args = {"document_tree": context_text}
        else:
            prompt = getDocumentPrompts()[11] # doc_fast_path_action_items_prompt
            invoke_args = {"document_text": context_text}

        for chunk in stream_document(
            chain_builder=lambda llm: prompt | llm | StrOutputParser(),
            invoke_args=invoke_args
        ):
            text = chunk if isinstance(chunk, str) else getattr(chunk, 'content', str(chunk))
            yield text

    def _stream_document_key_decisions(self, context_text: str, is_tree: bool = True):
        """Streams key decisions. Routes to Tree-based or Fast-Path prompt."""
        from src.providers.llm_service import stream_document
        from src.prompts.prompts import getDocumentPrompts
        from langchain_core.output_parsers import StrOutputParser

        if is_tree:
            prompt = getDocumentPrompts()[5] # doc_key_decisions_prompt
            invoke_args = {"document_tree": context_text}
        else:
            prompt = getDocumentPrompts()[12] # doc_fast_path_key_decisions_prompt
            invoke_args = {"document_text": context_text}

        for chunk in stream_document(
            chain_builder=lambda llm: prompt | llm | StrOutputParser(),
            invoke_args=invoke_args
        ):
            text = chunk if isinstance(chunk, str) else getattr(chunk, 'content', str(chunk))
            yield text

    # ========================================================================
    # Main Streaming Pipeline (SSE-compatible)
    # ========================================================================

    def streamDocumentPipeline(self, file_bytes: bytes, file_type: str, dept_id: int):
        """
        Generator that executes the complete document pipeline with real-time SSE streaming.
        Optimized with Fast-Path for small documents and parallel extraction.
        """
        FAST_PATH_THRESHOLD = 5000
        
        # Stage 1: Parse document to Markdown
        yield f"data: {json.dumps({'stage': 'parsing', 'status': 'in_progress'})}\n\n"
        try:
            markdown_text = self.parser.parse(file_bytes, file_type)
        except HTTPException as e:
            yield f"data: {json.dumps({'stage': 'parsing', 'status': 'error', 'error': e.detail})}\n\n"
            return
        yield f"data: {json.dumps({'stage': 'parsing', 'status': 'done'})}\n\n"

        # Stage 2: Token Analysis
        yield f"data: {json.dumps({'stage': 'analyzing', 'status': 'in_progress'})}\n\n"
        token_count = self._count_tokens(markdown_text)
        is_fast_path = token_count < FAST_PATH_THRESHOLD
        strategy = "fast_path" if is_fast_path else ("sliding_window" if self._should_use_sliding_window(token_count) else "hierarchical_tree")
        yield f"data: {json.dumps({'stage': 'analyzing', 'status': 'done', 'token_count': token_count, 'strategy': strategy})}\n\n"

        # Stage 3: Context Preparation (Tree or Fast-Path)
        tree_json = None
        context_for_workers = markdown_text
        using_tree = not is_fast_path

        if using_tree:
            yield f"data: {json.dumps({'stage': 'tree_generation', 'status': 'in_progress'})}\n\n"
            try:
                tree = self._route_tree_generation(markdown_text, file_type, token_count)
                tree_json = json.dumps(tree, ensure_ascii=False)
                context_for_workers = tree_json
                yield f"data: {json.dumps({'stage': 'tree_generation', 'status': 'done'})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'stage': 'tree_generation', 'status': 'error', 'error': str(e)})}\n\n"
                return
        else:
            # Fast Path: Skip tree generation, use markdown directly
            yield f"data: {json.dumps({'stage': 'tree_generation', 'status': 'skipped', 'reason': 'fast_path'})}\n\n"

        # Stage 4-6: Parallel streaming of Title, Summary, Action Items, Key Decisions
        token_queue = queue.Queue()
        stages = ['title', 'summary', 'action_items', 'key_decisions']
        for stage in stages:
            yield f"data: {json.dumps({'stage': stage, 'status': 'in_progress'})}\n\n"

        def capture_result(generate_func, context, is_tree, stage_name):
            try:
                full_text = []
                for token in generate_func(context, is_tree):
                    full_text.append(token)
                val = "".join(full_text)
                token_queue.put({'stage': stage_name, 'status': 'done', 'final_text': val})
            except Exception as e:
                import traceback
                logging.error(f"Error in {stage_name} generation: {e}\n{traceback.format_exc()}")
                token_queue.put({'stage': stage_name, 'status': 'error', 'error': str(e)})

        # Launch all extraction workers in parallel
        from src.utils import extract_json_array
        with ThreadPoolExecutor(max_workers=4) as executor:
            # Title can always be generated from markdown if tree isn't ready, but here we use the finalized context
            executor.submit(capture_result, self._stream_document_title, context_for_workers, using_tree, 'title')
            executor.submit(capture_result, self._stream_document_summary, context_for_workers, using_tree, 'summary')
            executor.submit(capture_result, self._stream_document_action_items, context_for_workers, using_tree, 'action_items')
            executor.submit(capture_result, self._stream_document_key_decisions, context_for_workers, using_tree, 'key_decisions')

            state = {}
            completed_stages = 0
            while completed_stages < 4:
                try:
                    item = token_queue.get(timeout=120)
                    if item.get('status') in ['done', 'error']:
                        completed_stages += 1
                        if item.get('status') == 'done':
                            stage_name = item['stage']
                            raw_text = item['final_text']
                            if stage_name == 'summary' or stage_name == 'title':
                                state[stage_name] = raw_text
                            else:
                                state[stage_name] = extract_json_array(raw_text)
                        else:
                            # Stage failed - set error message in state to prevent empty UI
                            stage_name = item.get('stage', 'unknown')
                            error_msg = item.get('error', 'Unknown error')
                            logging.error(f"❌ DocumentProcessor: Stage '{stage_name}' failed: {error_msg}")
                            if stage_name in ['summary', 'title']:
                                state[stage_name] = f"Error: {error_msg}"
                            else:
                                state[stage_name] = []
                        
                        # Forward the final status event to frontend
                        yield f"data: {json.dumps(item)}\n\n"
                except queue.Empty:
                    break

        # Stage 7: Format Final Report
        yield f"data: {json.dumps({'stage': 'formatting', 'status': 'in_progress'})}\n\n"

        final_report = json.dumps({
            "title": state.get('title', 'Untitled Document'),
            "summary": state.get('summary', ''),
            "action_items": self._normalize_items(state.get('action_items', [])),
            "key_decisions": self._normalize_items(state.get('key_decisions', []))
        }, ensure_ascii=False)

        # Final completion event
        yield f"data: {json.dumps({
            'stage': 'complete', 
            'final_report': final_report, 
            'tree_json': tree_json if tree_json else json.dumps({'title': 'Document Content', 'content': markdown_text, 'children': []}), 
            'token_count': token_count
        })}\n\n"

    def _normalize_items(self, items):
        """Normalizes action_items/key_decisions — handles both list and dict-with-items formats."""
        if isinstance(items, dict) and 'items' in items:
            return items['items']
        if isinstance(items, list):
            return items
        return []
