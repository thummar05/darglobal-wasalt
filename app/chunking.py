"""
Chunking and Text Normalization Module
Handles text cleaning, PII sanitization (phone numbers, emails),
and chunking for structured listings and narrative documents.
"""

import re
from typing import List, Dict, Any, Optional
import copy
import logging

logger = logging.getLogger(__name__)

# Regex patterns for sanitizing personal contact info (scraping ethics)
PHONE_REGEX = re.compile(
    r'(?:\+?966\s*(?:5\d|\d{2})|05\d|01\d)\s*\d{3,4}\s*\d{3,4}\b'
    r'|(?:\+?44\s*(?:[1-9]\d{1,4}))\s*\d{3,4}\s*\d{3,4}\b'
    r'|(?:\+?1\s*)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b'
)
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')

# Common web boilerplate to remove
BOILERPLATE_PATTERNS = [
    re.compile(r'RegisterFrom\.registerinterestdesc', re.IGNORECASE),
    re.compile(r'Scan QR code or click button to download app', re.IGNORECASE),
    re.compile(r'Click to go to URL', re.IGNORECASE),
    re.compile(r'Selling, buying, and renting… properties made easy with our apps!', re.IGNORECASE),
    re.compile(r'Enhance your experience with the Wasalt app!', re.IGNORECASE),
    re.compile(r'Grow your business\. Connect with clients easily\.', re.IGNORECASE),
    re.compile(r'We use cookies to enhance your browsing experience[^\n]*', re.IGNORECASE),
    re.compile(r'We value our privacy', re.IGNORECASE),
    re.compile(r'By clicking\s*[\u201c"]Accept[\u201d"]\s*,\s*you consent to our\s*(?:use of)?\s*cookies\.?', re.IGNORECASE),
    re.compile(r'\b(?:word\s+){4,}word\b', re.IGNORECASE),
]


def sanitize_text(text: str) -> str:
    """
    Remove sensitive personal contact information (phones, emails)
    and web scraping boilerplate.
    """
    if not text:
        return ""
    
    # Remove emails
    text = EMAIL_REGEX.sub("[REDACTED_EMAIL]", text)
    
    # Remove phone numbers
    text = PHONE_REGEX.sub("[REDACTED_PHONE]", text)
    
    # Remove boilerplate patterns
    for pattern in BOILERPLATE_PATTERNS:
        text = pattern.sub("", text)
    
    # Normalize whitespaces and blank lines
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    
    # Remove redundant duplicate adjacent lines
    cleaned_lines = []
    prev_line = None
    for line in text.splitlines():
        trimmed = line.strip()
        if trimmed and trimmed != prev_line:
            cleaned_lines.append(trimmed)
            prev_line = trimmed
        elif not trimmed and prev_line != "":
            cleaned_lines.append("")
            prev_line = ""
            
    return "\n".join(cleaned_lines).strip()


def estimate_tokens(text: str) -> int:
    """Rough token estimation (approx 4 chars per token)."""
    return max(1, len(text) // 4)


def split_text_into_chunks(
    text: str,
    chunk_size_tokens: int = 600,
    overlap_tokens: int = 100
) -> List[str]:
    """
    Split text into overlapping chunks using token estimations.
    Splits along paragraphs or sentences when possible.
    """
    if not text:
        return []
    
    # Character targets
    chunk_chars = chunk_size_tokens * 4
    overlap_chars = overlap_tokens * 4
    step_chars = max(chunk_chars - overlap_chars, 100)
    
    if len(text) <= chunk_chars:
        return [text]
    
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = []
    current_len = 0
    
    for p in paragraphs:
        p_len = len(p)
        if current_len + p_len + 2 <= chunk_chars:
            current_chunk.append(p)
            current_len += p_len + 2
        else:
            if current_chunk:
                chunk_str = "\n\n".join(current_chunk).strip()
                if chunk_str:
                    chunks.append(chunk_str)
                # Keep overlap from previous paragraphs if reasonable
                while current_chunk and sum(len(x) + 2 for x in current_chunk) > overlap_chars:
                    current_chunk.pop(0)
            
            if p_len > chunk_chars:
                # Break large paragraph by sentences
                sentences = re.split(r'(?<=[.!?؟\n])\s+', p)
                sub_chunk = []
                sub_len = 0
                for s in sentences:
                    if sub_len + len(s) + 1 <= chunk_chars:
                        sub_chunk.append(s)
                        sub_len += len(s) + 1
                    else:
                        if sub_chunk:
                            chunks.append(" ".join(sub_chunk).strip())
                            while sub_chunk and sum(len(x) + 1 for x in sub_chunk) > overlap_chars:
                                sub_chunk.pop(0)
                        sub_chunk.append(s)
                        sub_len = len(s)
                if sub_chunk:
                    current_chunk = [" ".join(sub_chunk)]
                    current_len = sum(len(x) + 2 for x in current_chunk)
            else:
                current_chunk.append(p)
                current_len = sum(len(x) + 2 for x in current_chunk)
                
    if current_chunk:
        remaining_str = "\n\n".join(current_chunk).strip()
        if remaining_str and (not chunks or remaining_str != chunks[-1]):
            chunks.append(remaining_str)
            
    return chunks


def chunk_text(
    text: str,
    metadata: Optional[Dict[str, Any]] = None,
    chunk_size: int = 600,
    overlap: int = 100
) -> List[Dict[str, Any]]:
    """
    Main chunking interface expected by ingest pipeline.
    Sanitizes text and produces a list of chunk dicts.
    """
    cleaned = sanitize_text(text)
    if not cleaned:
        return []
    
    base_meta = copy.deepcopy(metadata or {})
    raw_chunks = split_text_into_chunks(cleaned, chunk_size_tokens=chunk_size, overlap_tokens=overlap)
    
    result = []
    for idx, chunk_str in enumerate(raw_chunks):
        meta = copy.deepcopy(base_meta)
        meta["chunk_index"] = idx
        result.append({
            "text": chunk_str,
            "metadata": meta
        })
        
    return result
