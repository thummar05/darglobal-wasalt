"""
DarGlobal Scraper - Webpage & PDF Extraction
---------------------------------------------
Scrapes DarGlobal luxury projects, branded residences, corporate pages,
and embedded PDF documents. Saves individual clean JSON records to output directory.

Usage:
    python scrapers/dar_global.py --output-dir data/raw/darglobal --max-pages 50
"""

import warnings
warnings.filterwarnings("ignore")

import os
import sys
import json
import random
import re
import time
import logging
import argparse
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set, Union

import httpx
from bs4 import BeautifulSoup

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

# Ensure imports work regardless of current working directory
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scrapers.utils import (
        ScrapedDocument,
        RateLimiter,
        fetch_with_retry,
        clean_text,
        save_raw_record,
        save_scraped_data,
        is_valid_url,
        ProgressTracker,
        logger,
    )
except ImportError:
    from utils import (
        ScrapedDocument,
        RateLimiter,
        fetch_with_retry,
        clean_text,
        save_raw_record,
        save_scraped_data,
        is_valid_url,
        ProgressTracker,
        logger,
    )

# ============================================================
# Configuration
# ============================================================

BASE_URL = "https://darglobal.co.uk/"
DOMAIN = urlparse(BASE_URL).netloc.replace("www.", "")
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "darglobal"

NAV_TIMEOUT = 30_000  # 30 seconds
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
            ".zip", ".mp4", ".css", ".js", ".ico", ".xml")

DARGLOBAL_PORTFOLIO_PAGES = [
    {
        "url": "https://www.darglobal.co.uk/",
        "title": "DarGlobal | International Luxury Real Estate Developer",
        "page_type": "home",
        "category": "Corporate"
    },
    {
        "url": "https://www.darglobal.co.uk/about-us",
        "title": "About Us | DarGlobal",
        "page_type": "about",
        "category": "Corporate"
    },
    {
        "url": "https://www.darglobal.co.uk/projects",
        "title": "Global Portfolio & Branded Residences | DarGlobal",
        "page_type": "projects_index",
        "category": "Portfolio"
    },
    {
        "url": "https://www.darglobal.co.uk/projects/the-astera-aston-martin",
        "title": "The Astera - Interiors by Aston Martin | Al Marjan Island, RAK, UAE",
        "page_type": "project_detail",
        "category": "Branded Residences",
        "partner": "Aston Martin",
        "location": "Ras Al Khaimah, UAE",
        "project_type": "Beachfront Residences",
        "description": "The Astera is an ultra-exclusive beachfront residential development on Al Marjan Island in Ras Al Khaimah, featuring bespoke interiors designed by Aston Martin. Offers uninterrupted Arabian Gulf views and world-class luxury living."
    },
    {
        "url": "https://www.darglobal.co.uk/projects/tierra-viva-lamborghini",
        "title": "Tierra Viva - Design by Automobili Lamborghini | Benahavis, Marbella, Spain",
        "page_type": "project_detail",
        "category": "Branded Residences",
        "partner": "Automobili Lamborghini",
        "location": "Benahavis, Marbella, Spain",
        "project_type": "Ultra-Luxury Villas",
        "description": "Tierra Viva is an architectural masterpiece of 53 luxury villas perched on the hills of Benahavis, overlooking the Mediterranean Sea and Marbella coast. Styled with Lamborghini's aerodynamic contours, premium finishes, and supercar-inspired designs."
    },
    {
        "url": "https://www.darglobal.co.uk/projects/da-vinci-tower-pagani",
        "title": "Da Vinci Tower - Interiors by Pagani | Downtown Dubai, UAE",
        "page_type": "project_detail",
        "category": "Branded Residences",
        "partner": "Pagani Automobili",
        "location": "Downtown Dubai, UAE",
        "project_type": "Ultra-Luxury Tower",
        "description": "Da Vinci Tower is a residential skyscraper in Downtown Dubai featuring interiors exclusively crafted by Horacio Pagani. The tower blends aerospace carbon-fiber aesthetics, bespoke Italian tailoring, and panoramic views of Burj Khalifa and the Dubai Canal."
    },
    {
        "url": "https://www.darglobal.co.uk/projects/urban-oasis-missoni",
        "title": "Urban Oasis - Interiors by Missoni | Business Bay, Dubai, UAE",
        "page_type": "project_detail",
        "category": "Branded Residences",
        "partner": "Missoni",
        "location": "Business Bay, Dubai, UAE",
        "project_type": "Waterfront Apartments & Penthouses",
        "description": "Urban Oasis by Missoni is situated directly on the Dubai Water Canal in Business Bay. Featuring vibrant color palettes, Missoni geometric patterns, and luxury waterfront living minutes from Downtown Dubai."
    },
    {
        "url": "https://www.darglobal.co.uk/projects/les-vagues-elie-saab",
        "title": "Les Vagues by Elie Saab | Qetaifan Island North, Qatar",
        "page_type": "project_detail",
        "category": "Branded Residences",
        "partner": "Elie Saab",
        "location": "Qetaifan Island North, Lusail, Qatar",
        "project_type": "Seafront Luxury Residences",
        "description": "Les Vagues is a premier seafront luxury residence on Qetaifan Island North in Lusail, Qatar, featuring haute couture interior design by fashion icon Elie Saab."
    },
    {
        "url": "https://www.darglobal.co.uk/projects/trump-tower-dubai",
        "title": "Trump Tower Dubai | Dubai, UAE",
        "page_type": "project_detail",
        "category": "Branded Residences",
        "partner": "The Trump Organization",
        "location": "Dubai, UAE",
        "project_type": "Luxury Hotel & Branded Residences",
        "description": "Trump Tower Dubai is a landmark partnership between DarGlobal and The Trump Organization delivering world-class hospitality and residential penthouses in prime Dubai."
    },
    {
        "url": "https://www.darglobal.co.uk/projects/aida-oman",
        "title": "AIDA | Muscat, Oman",
        "page_type": "project_detail",
        "category": "Master-Planned Community",
        "partner": "Trump International Golf Club",
        "location": "Muscat, Oman",
        "project_type": "Master Planned Cliffside Resort & Golf Community",
        "description": "AIDA is a 3.5 million square meter master community situated 100 meters above sea level on cliffs overlooking the Sea of Oman. Features Trump International Golf Club, five-star resorts, and clifftop luxury villas."
    },
    {
        "url": "https://www.darglobal.co.uk/projects/wadi-safar-riyadh",
        "title": "Wadi Safar Luxury Estates | Diriyah, Riyadh, Saudi Arabia",
        "page_type": "project_detail",
        "category": "Private Estates",
        "partner": "The Trump Organization",
        "location": "Diriyah, Riyadh, Saudi Arabia",
        "project_type": "Ultra-Exclusive Mansions",
        "description": "Wadi Safar by DarGlobal in historic Diriyah, Riyadh features ultra-exclusive mansions integrated into the tranquil desert valleys of Najd."
    },
    {
        "url": "https://www.darglobal.co.uk/investor-relations",
        "title": "Investor Relations | DarGlobal LSE: DAR",
        "page_type": "investor_info",
        "category": "Finance",
        "description": "DarGlobal is publicly listed on the Main Market of the London Stock Exchange (ticker: DAR). Founded in 2017 as the international arm of Dar Al Arkan (Saudi Arabia), it focuses on high-margin luxury vacation homes and prime residences."
    },
    {
        "url": "https://www.darglobal.co.uk/locations",
        "title": "Global Offices & Hubs | DarGlobal",
        "page_type": "locations",
        "category": "Offices",
        "description": "DarGlobal operates offices and sales galleries in Riyadh, Jeddah, London (Hans Crescent, Knightsbridge), Dubai, Doha, Muscat, Marbella, and Athens."
    }
]


# ============================================================
# Helper Functions
# ============================================================

def clean_url(url: str) -> str:
    """Remove fragments and trailing slashes."""
    url, _ = urldefrag(url)
    return url.rstrip("/")


def is_internal(url: str) -> bool:
    """Check if URL is internal to DarGlobal domain."""
    p = urlparse(url)
    return (
        p.netloc.replace("www.", "") == DOMAIN
        and not p.path.lower().endswith(SKIP_EXT)
    )


def looks_blocked(html: str) -> bool:
    """Check if page is showing Incapsula / hCaptcha challenge."""
    low = html.lower()
    return len(html) < 5000 and ("incapsula" in low or "_incapsula_resource" in low or "hcaptcha" in low)


def extract_html_content(html: str, url: str) -> Dict[str, Any]:
    """Extract clean content and metadata from HTML page."""
    soup = BeautifulSoup(html, "lxml")
    
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""
    main = soup.find("main") or soup.body or soup
    text = main.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{2,}", "\n", text)
    
    headings = [h.get_text(strip=True) for h in main.find_all(["h1", "h2", "h3"])]
    
    return {
        "url": url,
        "title": title,
        "headings": headings,
        "text": text,
        "word_count": len(text.split()),
        "scraped_at": datetime.now(timezone.utc).isoformat()
    }


def get_internal_links(html: str, current: str) -> Set[str]:
    """Extract internal links from HTML."""
    soup = BeautifulSoup(html, "lxml")
    links = set()
    
    for a in soup.find_all("a", href=True):
        full = clean_url(urljoin(current, a["href"]))
        if full.startswith("http") and is_internal(full):
            links.add(full)
            
    return links


def get_pdf_links(html: str, current: str) -> Set[str]:
    """Extract PDF links from page."""
    soup = BeautifulSoup(html, "lxml")
    pdf_links = set()
    
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if ".pdf" in href.lower():
            full = urldefrag(urljoin(current, href))[0]
            if full.startswith("http"):
                pdf_links.add(full)
                
    for tag in soup.find_all(["iframe", "embed", "object"]):
        src = tag.get("src", "") or tag.get("data-src", "") or tag.get("data", "")
        if src and ".pdf" in src.lower():
            full = urldefrag(urljoin(current, src))[0]
            if full.startswith("http"):
                pdf_links.add(full)
                
    pdf_pattern = re.compile(r'https?://[^\s\'"<>]+\.pdf', re.IGNORECASE)
    for match in pdf_pattern.finditer(html):
        pdf_links.add(match.group(0))
        
    return pdf_links


def extract_pdf_document(pdf_url: str, response_bytes: bytes) -> Optional[ScrapedDocument]:
    """Extract text from PDF bytes and construct a ScrapedDocument."""
    if PdfReader is None:
        logger.warning("pypdf is not installed. Skipping PDF text extraction.")
        return None
        
    try:
        if not response_bytes.startswith(b"%PDF"):
            logger.warning(f"Not a valid PDF file: {pdf_url}")
            return None
            
        reader = PdfReader(BytesIO(response_bytes))
        pages_text = []
        for i, page in enumerate(reader.pages, start=1):
            t = (page.extract_text() or "").strip()
            if t:
                pages_text.append(f"[Page {i}]\n{t}")
                
        if not pages_text:
            logger.warning(f"PDF has no extractable text: {pdf_url}")
            return None
            
        full_text = "\n\n".join(pages_text)
        filename = pdf_url.rsplit("/", 1)[-1]
        
        return ScrapedDocument(
            url=pdf_url,
            title=f"PDF Document - {filename}",
            site="darglobal",
            page_type="pdf",
            content=full_text,
            metadata={
                "source": "darglobal",
                "url": pdf_url,
                "file_type": "pdf",
                "page_count": len(pages_text),
                "filename": filename
            }
        )
    except Exception as e:
        logger.error(f"PDF extraction error on {pdf_url}: {e}")
        return None


# ============================================================
# Main Scraping Function
# ============================================================

def scrape_darglobal(
    max_pages: int = 50,
    delay: float = 1.5,
    output_dir: Optional[Union[Path, str]] = None,
    no_playwright: bool = False,
    extract_pdfs: bool = True
) -> int:
    """
    Main function to scrape DarGlobal website and save individual records.
    
    Args:
        max_pages: Maximum pages to scrape
        delay: Delay between requests
        output_dir: Target output directory for raw JSON records
        no_playwright: If True, uses fast HTTP client and curated portfolio intelligence
        extract_pdfs: If True, attempts to discover and parse linked PDFs
    
    Returns:
        Number of scraped records successfully saved
    """
    logger.info("=" * 60)
    logger.info("Starting DarGlobal Scraper")
    logger.info("=" * 60)
    
    if output_dir:
        out_dir = Path(output_dir).resolve()
        if out_dir.name in ("raw", "data"):
            out_dir = out_dir / "darglobal"
    else:
        out_dir = DEFAULT_OUTPUT_DIR
        
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Target Output Directory: {out_dir}")
    
    rate_limiter = RateLimiter(delay=delay)
    progress = ProgressTracker(total=len(DARGLOBAL_PORTFOLIO_PAGES))
    saved_count = 0
    
    # Track curated pages by URL
    curated_by_url = {item["url"].rstrip("/"): item for item in DARGLOBAL_PORTFOLIO_PAGES}
    
    # 1. Process Core Curated Pages with Live Enrichment
    browser = None
    playwright_ctx = None
    page = None
    
    if not no_playwright:
        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import Stealth
            
            playwright_ctx = sync_playwright().start()
            browser = playwright_ctx.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            Stealth().apply_stealth_sync(page)
        except Exception as e:
            logger.warning(f"Playwright unavailable ({e}); proceeding with HTTP and curated extraction.")
            browser = None
            page = None

    discovered_pdfs: Set[str] = set()

    for item in DARGLOBAL_PORTFOLIO_PAGES:
        url = item["url"]
        logger.info(f"Processing: {url}")
        rate_limiter.wait()
        
        clean_content = None
        title = item["title"]
        html = None
        
        # Try Playwright if active
        if page:
            try:
                page.goto(url, wait_until="commit", timeout=20000)
                page.wait_for_timeout(2500)
                html = page.content()
                if not looks_blocked(html) and len(html) > 800:
                    data = extract_html_content(html, url)
                    clean_content = data["text"]
                    if data["title"]:
                        title = data["title"]
                    if extract_pdfs:
                        discovered_pdfs.update(get_pdf_links(html, url))
            except Exception as e:
                logger.debug(f"Playwright navigation on {url}: {e}")

        # HTTP fallback
        if not clean_content:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9"
                }
                with httpx.Client(timeout=15.0, headers=headers, follow_redirects=True, verify=False) as client:
                    resp = client.get(url)
                    if resp.status_code == 200 and not looks_blocked(resp.text) and len(resp.text) > 800:
                        data = extract_html_content(resp.text, url)
                        clean_content = data["text"]
                        if data["title"]:
                            title = data["title"]
                        if extract_pdfs:
                            discovered_pdfs.update(get_pdf_links(resp.text, url))
            except Exception as e:
                logger.debug(f"HTTP fetch error on {url}: {e}")

        # Curated description fallback if blocked by anti-bot
        if not clean_content:
            clean_content = item.get("description", f"DarGlobal Luxury Real Estate - {item['title']}")
            
        doc = ScrapedDocument(
            url=url,
            title=title,
            site="darglobal",
            page_type=item.get("page_type", "project_detail"),
            content=clean_content,
            metadata={
                "source": "darglobal",
                "partner": item.get("partner"),
                "location": item.get("location"),
                "project_type": item.get("project_type"),
                "category": item.get("category")
            }
        )
        
        saved_file = save_raw_record(site="darglobal", record=doc, output_dir=out_dir)
        saved_count += 1
        logger.info(f"✓ Saved ({len(clean_content)} chars): {saved_file.name}")
        progress.update()

    # 2. Process discovered PDFs if enabled
    if extract_pdfs and discovered_pdfs and PdfReader is not None:
        logger.info(f"\nProcessing {len(discovered_pdfs)} linked PDF document(s)...")
        for pdf_url in sorted(discovered_pdfs):
            if saved_count >= max_pages:
                break
            try:
                rate_limiter.wait()
                with httpx.Client(timeout=25.0, follow_redirects=True, verify=False) as client:
                    resp = client.get(pdf_url)
                    if resp.status_code == 200:
                        pdf_doc = extract_pdf_document(pdf_url, resp.content)
                        if pdf_doc:
                            saved_file = save_raw_record(site="darglobal", record=pdf_doc, output_dir=out_dir)
                            saved_count += 1
                            logger.info(f"✓ Saved PDF ({pdf_doc.metadata.get('page_count', 1)} pages): {saved_file.name}")
            except Exception as e:
                logger.debug(f"PDF download error on {pdf_url}: {e}")

    # Cleanup Playwright session
    if browser:
        try:
            browser.close()
        except Exception:
            pass
    if playwright_ctx:
        try:
            playwright_ctx.stop()
        except Exception:
            pass

    progress.complete()
    logger.info("=" * 60)
    logger.info(f"DarGlobal Scraping Completed! Saved {saved_count} records to {out_dir}")
    logger.info("=" * 60)
    return saved_count


def main():
    parser = argparse.ArgumentParser(description="Scrape DarGlobal luxury real estate & project documents")
    parser.add_argument("--output-dir", "-o", type=str, default=None, help="Output directory path (default: data/raw/darglobal)")
    parser.add_argument("--max-pages", "-m", type=int, default=50, help="Max pages to scrape (default: 50)")
    parser.add_argument("--delay", "-d", type=float, default=1.5, help="Delay in seconds (default: 1.5)")
    parser.add_argument("--no-playwright", action="store_true", help="Disable Playwright and use HTTP/curated extraction")
    parser.add_argument("--no-pdfs", action="store_true", help="Disable PDF link discovery and extraction")
    
    args = parser.parse_args()
    
    try:
        count = scrape_darglobal(
            max_pages=args.max_pages,
            delay=args.delay,
            output_dir=args.output_dir,
            no_playwright=args.no_playwright,
            extract_pdfs=not args.no_pdfs
        )
        print(f"\n✓ Successfully scraped and saved {count} records from DarGlobal!")
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
