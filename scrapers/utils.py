import warnings
warnings.filterwarnings("ignore")

import os
import json
import time
import re
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from urllib.parse import urlparse
import httpx
import trafilatura
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("scraper_utils")


class ScrapedDocument(BaseModel):
    url: str
    title: str
    site: str
    page_type: str = "general"
    content: str
    raw_html: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    scraped_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RateLimiter:
    """Simple rate limiter to enforce delays between network requests."""
    def __init__(self, delay: float = 1.5):
        self.delay = delay
        self.last_call = 0.0

    def wait(self):
        elapsed = time.time() - self.last_call
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self.last_call = time.time()


class ProgressTracker:
    """Track and log scraping progress."""
    def __init__(self, total: int):
        self.total = total
        self.current = 0

    def update(self):
        self.current += 1
        pct = (self.current / self.total) * 100 if self.total > 0 else 100
        logger.info(f"Progress: [{self.current}/{self.total}] ({pct:.1f}%)")

    def complete(self):
        logger.info(f"Scraping completed! Processed {self.current}/{self.total} items.")


def is_valid_url(url: str) -> bool:
    """Validate URL syntax."""
    try:
        parsed = urlparse(url)
        return bool(parsed.scheme in ("http", "https") and parsed.netloc)
    except Exception:
        return False


def clean_text(text: str) -> str:
    """Normalize and clean whitespace from text."""
    if not text:
        return ""
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def fetch_with_retry(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    max_retries: int = 3,
    timeout: float = 20.0
) -> Optional[httpx.Response]:
    """Fetch URL using httpx with automatic retry and timeout handling."""
    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True, verify=False) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    return resp
                elif resp.status_code in (301, 302, 307, 308):
                    return resp
                elif resp.status_code == 404:
                    logger.warning(f"HTTP 404 on {url}")
                    return None
                else:
                    logger.warning(f"HTTP {resp.status_code} on {url} (attempt {attempt}/{max_retries})")
        except Exception as e:
            logger.warning(f"Request error on {url} (attempt {attempt}/{max_retries}): {e}")
        time.sleep(1.0 * attempt)
    return None


def check_robots_txt(base_url: str) -> Dict[str, Any]:
    """Check availability of robots.txt for a site."""
    robots_url = f"{base_url.rstrip('/')}/robots.txt"
    resp = fetch_with_retry(robots_url)
    if resp and resp.status_code == 200:
        return {"accessible": True, "note": f"robots.txt accessible at {robots_url}"}
    return {"accessible": False, "note": f"robots.txt unavailable or blocked at {robots_url}"}


def save_scraped_data(data: List[Dict[str, Any]], site_name: str, output_dir: Optional[Union[Path, str]] = None) -> Path:
    """Save a list of scraped dictionaries to data/raw/{site_name}/."""
    if output_dir is None:
        target_dir = Path(__file__).resolve().parent.parent / "data" / "raw" / site_name
    else:
        target_dir = Path(output_dir).resolve()
        if target_dir.name in ("raw", "data"):
            target_dir = target_dir / site_name
    target_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = target_dir / f"{site_name}_batch_{timestamp}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return out_file


def url_to_filename(url: str, max_length: int = 120) -> str:
    """Generate a clean, deterministic, filesystem-safe filename from a URL."""
    clean_url = re.sub(r"^https?://", "", url)
    clean_url = re.sub(r"[^\w\-.]", "_", clean_url)
    clean_url = re.sub(r"_+", "_", clean_url).strip("._")
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    if len(clean_url) > max_length:
        clean_url = clean_url[:max_length]
    return f"{clean_url}_{url_hash}.json"


def save_raw_record(site: str, record: ScrapedDocument, output_dir: Optional[Union[Path, str]] = None) -> Path:
    """Save a single ScrapedDocument as JSON in data/raw/{site}/ or specified output_dir."""
    if output_dir is None:
        base_dir = Path(__file__).resolve().parent.parent / "data" / "raw" / site
    else:
        base_dir = Path(output_dir).resolve()
        if base_dir.name in ("raw", "data"):
            base_dir = base_dir / site
    base_dir.mkdir(parents=True, exist_ok=True)
    filename = url_to_filename(record.url)
    file_path = base_dir / filename
    data = record.model_dump(exclude_none=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return file_path


def extract_clean_text(html: str) -> str:
    """Extract clean text using trafilatura with BeautifulSoup fallback."""
    extracted = trafilatura.extract(
        html,
        include_links=False,
        include_images=False,
        output_format="txt"
    )
    if extracted and len(extracted.strip()) > 50:
        return extracted.strip()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text().splitlines()]
    return "\n".join([line for line in lines if line])


def extract_title(html: str, fallback_url: str = "") -> str:
    """Extract page title from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        return title_tag.string.strip()
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()
    h1_tag = soup.find("h1")
    if h1_tag and h1_tag.text:
        return h1_tag.text.strip()
    return fallback_url
