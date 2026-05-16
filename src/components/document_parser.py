"""
Document Parser — Smart Normalizer for Vectorless RAG Pipeline.

Converts PDF, DOCX, TXT, and MD files into structured Markdown
with explicit headings for downstream tree generation.
"""

import sys
import io
import re

from fastapi import HTTPException
from src.exception import CustomException
from src.logger import logging


class DocumentParser:
    """Parses uploaded documents into structured Markdown text."""
    
    SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.txt', '.md'}
    
    def parse(self, file_bytes: bytes, file_type: str) -> str:
        """
        Main entry point. Routes to the correct parser based on file type.
        Returns structured Markdown text.
        """
        try:
            file_type = file_type.lower().strip('.')
            logging.info(f"📄 DocumentParser: Parsing file of type '{file_type}'")
            
            if file_type == 'pdf':
                markdown_text = self._parse_pdf(file_bytes)
            elif file_type == 'docx':
                markdown_text = self._parse_docx(file_bytes)
            elif file_type == 'txt':
                markdown_text = self._parse_txt(file_bytes)
            elif file_type == 'md':
                markdown_text = self._parse_md(file_bytes)
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_type}")
            
            self._validate_content(markdown_text)
            logging.info(f"📄 DocumentParser: Successfully parsed {len(markdown_text)} characters")
            return markdown_text
            
        except HTTPException:
            raise
        except Exception as e:
            raise CustomException(e, sys)
    
    def _parse_pdf(self, file_bytes: bytes) -> str:
        """
        Extracts text from PDF using pdfplumber with font-size heuristics.
        Lines with large font sizes or bold text get Markdown heading prefixes.
        """
        try:
            import pdfplumber
            
            markdown_lines = []
            pdf = pdfplumber.open(io.BytesIO(file_bytes))
            
            for page_num, page in enumerate(pdf.pages):
                # Extract words with their font metadata
                words = page.extract_words(extra_attrs=['fontname', 'size'])
                
                if not words:
                    # Fallback: extract plain text if word-level extraction fails
                    text = page.extract_text()
                    if text:
                        markdown_lines.append(text)
                    continue
                
                # Group words into lines by their y-coordinate (top)
                lines_by_y = {}
                for word in words:
                    y_key = round(word['top'], 1)
                    if y_key not in lines_by_y:
                        lines_by_y[y_key] = []
                    lines_by_y[y_key].append(word)
                
                for y_key in sorted(lines_by_y.keys()):
                    line_words = sorted(lines_by_y[y_key], key=lambda w: w['x0'])
                    line_text = ' '.join(w['text'] for w in line_words).strip()
                    
                    if not line_text:
                        continue
                    
                    # Determine heading level from font size
                    avg_size = sum(w.get('size', 12) for w in line_words) / len(line_words)
                    is_bold = any('bold' in w.get('fontname', '').lower() for w in line_words)
                    
                    if avg_size >= 18 or (avg_size >= 16 and is_bold):
                        markdown_lines.append(f"\n# {line_text}\n")
                    elif avg_size >= 14 or (avg_size >= 13 and is_bold):
                        markdown_lines.append(f"\n## {line_text}\n")
                    elif is_bold and len(line_text) < 100:
                        markdown_lines.append(f"\n### {line_text}\n")
                    else:
                        markdown_lines.append(line_text)
            
            pdf.close()
            return '\n'.join(markdown_lines)
            
        except Exception as e:
            logging.error(f"PDF parsing failed: {e}")
            # Fallback: try simple text extraction
            try:
                import pdfplumber
                pdf = pdfplumber.open(io.BytesIO(file_bytes))
                text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
                pdf.close()
                return text
            except Exception as fallback_error:
                raise CustomException(fallback_error, sys)
    
    def _parse_docx(self, file_bytes: bytes) -> str:
        """
        Extracts text from DOCX using python-docx with style mapping.
        Maps Heading styles to Markdown heading levels.
        """
        try:
            from docx import Document
            
            doc = Document(io.BytesIO(file_bytes))
            markdown_lines = []
            
            for paragraph in doc.paragraphs:
                text = paragraph.text.strip()
                if not text:
                    markdown_lines.append('')
                    continue
                
                style_name = (paragraph.style.name or '').lower()
                
                # Map DOCX styles to Markdown headings
                if 'heading 1' in style_name or 'title' in style_name:
                    markdown_lines.append(f"\n# {text}\n")
                elif 'heading 2' in style_name:
                    markdown_lines.append(f"\n## {text}\n")
                elif 'heading 3' in style_name:
                    markdown_lines.append(f"\n### {text}\n")
                elif 'heading' in style_name:
                    markdown_lines.append(f"\n### {text}\n")
                elif paragraph.runs and all(run.bold for run in paragraph.runs if run.text.strip()):
                    # Bold paragraphs that aren't headings get ### treatment
                    if len(text) < 100:
                        markdown_lines.append(f"\n### {text}\n")
                    else:
                        markdown_lines.append(text)
                else:
                    markdown_lines.append(text)
            
            return '\n'.join(markdown_lines)
            
        except Exception as e:
            raise CustomException(e, sys)
    
    def _parse_txt(self, file_bytes: bytes) -> str:
        """Returns raw text as-is. TXT files have no structural metadata."""
        try:
            text = file_bytes.decode('utf-8', errors='replace')
            return text.strip()
        except Exception as e:
            raise CustomException(e, sys)
    
    def _parse_md(self, file_bytes: bytes) -> str:
        """Returns Markdown text directly — already structured."""
        try:
            text = file_bytes.decode('utf-8', errors='replace')
            return text.strip()
        except Exception as e:
            raise CustomException(e, sys)
    
    def detect_is_flat(self, markdown_text: str) -> bool:
        """
        Checks if the output has zero Markdown headings.
        If flat, triggers Semantic Reconstruction in the pipeline.
        """
        heading_pattern = re.compile(r'^#{1,3}\s+\S', re.MULTILINE)
        matches = heading_pattern.findall(markdown_text)
        is_flat = len(matches) < 2  # Less than 2 headings = essentially flat
        if is_flat:
            logging.info("📄 DocumentParser: Document detected as FLAT (no structural headings)")
        return is_flat
    
    def _validate_content(self, text: str) -> None:
        """Raises HTTPException if text is empty (encrypted/image-only PDF edge case)."""
        cleaned = text.strip()
        if not cleaned or len(cleaned) < 50:
            raise HTTPException(
                status_code=400, 
                detail="Could not extract readable text from the uploaded file. The file may be encrypted, image-only, or empty."
            )
