"""
DarGlobal Scraper - Improved Version with PDF Support
------------------------------------------------------
Handles:
1. Regular webpage content
2. Embedded PDFs in iframes/embed tags
3. Direct PDF links
4. PDF extraction and text parsing

Install:
    pip install playwright beautifulsoup4 lxml pypdf
    playwright install chromium

Usage:
    python scrapers/dar_global_improved.py
"""

import json
import random
import re
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from pypdf import PdfReader

# ============================================================
# Configuration
# ============================================================

BASE = "https://darglobal.co.uk/"
DOMAIN = urlparse(BASE).netloc.replace("www.", "")

# Resolve project directories relative to this file
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "data" / "raw" / "darglobal"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_FILE = OUT_DIR / f"darglobal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
PDF_FILE = OUT_DIR / f"darglobal_pdfs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = DATA_DIR / "links_cache.json"
FAILED_FILE = DATA_DIR / "failed_urls.txt"
PROFILE_DIR = PROJECT_ROOT / "browser_profile"

MAX_PAGES = 60
NAV_TIMEOUT = 30_000  # 30 seconds

SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
            ".zip", ".mp4", ".css", ".js", ".ico", ".xml")


# ============================================================
# Helper Functions
# ============================================================

def load_json(path: Path, default):
    """Load JSON file with error handling"""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return default


def save_json(path: Path, data):
    """Save data to JSON file"""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def clean_url(url: str) -> str:
    """Remove fragments and trailing slashes"""
    url, _ = urldefrag(url)
    return url.rstrip("/")


def is_internal(url: str) -> bool:
    """Check if URL is internal to the site"""
    p = urlparse(url)
    return (
        p.netloc.replace("www.", "") == DOMAIN
        and not p.path.lower().endswith(SKIP_EXT)
    )


def looks_blocked(html: str) -> bool:
    """Check if page is showing Incapsula challenge"""
    low = html.lower()
    return len(html) < 5000 and ("incapsula" in low or "_incapsula_resource" in low)


# ============================================================
# Content Extraction
# ============================================================

def extract_text(html: str, url: str) -> dict:
    """Extract text content from HTML page"""
    soup = BeautifulSoup(html, "lxml")
    
    # Remove unwanted tags
    for tag in soup(["script", "style", "noscript", "svg",
                     "nav", "footer", "header", "form"]):
        tag.decompose()

    # Get title
    title = soup.title.get_text(strip=True) if soup.title else ""
    
    # Get main content
    main = soup.find("main") or soup.body or soup
    text = main.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{2,}", "\n", text)
    
    # Get headings
    headings = [h.get_text(strip=True) for h in main.find_all(["h1", "h2", "h3"])]
    
    return {
        "url": url,
        "title": title,
        "type": "webpage",
        "headings": headings,
        "text": text,
        "word_count": len(text.split()),
        "scraped_at": datetime.now().isoformat()
    }


def get_links(html: str, current: str) -> set:
    """Extract internal links from HTML"""
    soup = BeautifulSoup(html, "lxml")
    links = set()
    
    for a in soup.find_all("a", href=True):
        full = clean_url(urljoin(current, a["href"]))
        if full.startswith("http") and is_internal(full):
            links.add(full)
    
    return links


def get_pdf_links(html: str, current: str) -> set:
    """
    Extract PDF links from page - comprehensive approach.
    
    Looks for:
    1. Direct <a href="*.pdf"> links
    2. Embedded PDFs in <iframe> tags
    3. Embedded PDFs in <embed> tags
    4. Embedded PDFs in <object> tags
    5. PDF URLs in data-* attributes
    6. PDF URLs in JavaScript/text content
    """
    soup = BeautifulSoup(html, "lxml")
    pdf_links = set()
    
    # Method 1: Direct links <a href="*.pdf">
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ".pdf" in href.lower():
            full = urldefrag(urljoin(current, href))[0]
            if full.startswith("http"):
                pdf_links.add(full)
    
    # Method 2: Iframes <iframe src="*.pdf">
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "") or iframe.get("data-src", "")
        if src and ".pdf" in src.lower():
            full = urldefrag(urljoin(current, src))[0]
            if full.startswith("http"):
                pdf_links.add(full)
    
    # Method 3: Embed tags <embed src="*.pdf">
    for embed in soup.find_all("embed"):
        src = embed.get("src", "") or embed.get("data-src", "")
        if src and ".pdf" in src.lower():
            full = urldefrag(urljoin(current, src))[0]
            if full.startswith("http"):
                pdf_links.add(full)
    
    # Method 4: Object tags <object data="*.pdf">
    for obj in soup.find_all("object"):
        data_attr = obj.get("data", "")
        if data_attr and ".pdf" in data_attr.lower():
            full = urldefrag(urljoin(current, data_attr))[0]
            if full.startswith("http"):
                pdf_links.add(full)
    
    # Method 5: Search in all src/data attributes
    for tag in soup.find_all(True):
        for attr in ["src", "data-src", "data-url", "data-file", "data-pdf"]:
            value = tag.get(attr, "")
            if value and ".pdf" in value.lower():
                full = urldefrag(urljoin(current, value))[0]
                if full.startswith("http"):
                    pdf_links.add(full)
    
    # Method 6: Search in HTML text for PDF URLs
    # Useful for JavaScript-embedded URLs
    pdf_pattern = re.compile(r'https?://[^\s\'"<>]+\.pdf', re.IGNORECASE)
    for match in pdf_pattern.finditer(html):
        url = match.group(0)
        if DOMAIN in url:  # Only internal PDFs
            pdf_links.add(url)
    
    return pdf_links


# ============================================================
# PDF Processing
# ============================================================

def extract_pdf_content(pdf_url: str, context, page=None) -> dict:
    """
    Download and extract text from PDF.
    Tries multiple methods to handle protected PDFs.
    
    Args:
        pdf_url: URL of the PDF
        context: Playwright browser context (reuses cookies)
        page: Playwright page object (optional, for navigation method)
    
    Returns:
        Dictionary with PDF content
    """
    try:
        print(f"  📄 Downloading PDF: {pdf_url}")
        
        # Method 1: Try direct download with referrer
        try:
            response = context.request.get(
                pdf_url, 
                timeout=30_000,
                headers={
                    "Referer": "https://darglobal.co.uk/",
                    "Accept": "application/pdf,*/*",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            )
            
            if response.ok and response.body().startswith(b"%PDF"):
                pdf_bytes = response.body()
            else:
                raise Exception(f"HTTP {response.status}")
        
        except Exception as e1:
            print(f"  ⚠ Direct download failed ({e1}), trying navigation method...")
            
            # Method 2: Navigate to PDF in browser, then get response
            if page:
                try:
                    # Navigate to the PDF URL
                    pdf_response = page.goto(pdf_url, wait_until="load", timeout=30_000)
                    
                    if pdf_response and pdf_response.ok:
                        pdf_bytes = pdf_response.body()
                    else:
                        raise Exception("Navigation failed")
                
                except Exception as e2:
                    print(f"  ✗ Both methods failed: Direct={e1}, Navigation={e2}")
                    return None
            else:
                print(f"  ✗ Failed to download (HTTP {response.status if 'response' in locals() else 'N/A'})")
                return None
        
        # Check if it's really a PDF
        if not pdf_bytes.startswith(b"%PDF"):
            print("  ✗ Not a valid PDF file")
            return None
        
        # Extract text from PDF
        reader = PdfReader(BytesIO(pdf_bytes))
        pages = []
        
        for i, page_item in enumerate(reader.pages, start=1):
            text = (page_item.extract_text() or "").strip()
            if text:
                pages.append({
                    "page": i,
                    "text": text
                })
        
        if not pages:
            print("  ⚠ PDF has no extractable text (might be scanned)")
            return None
        
        # Combine all page text
        full_text = "\n\n".join(p["text"] for p in pages)
        
        # Get filename from URL
        filename = pdf_url.rsplit("/", 1)[-1]
        
        print(f"  ✓ Extracted {len(pages)} pages, {len(full_text.split())} words")
        
        return {
            "url": pdf_url,
            "title": filename,
            "type": "pdf",
            "pages": pages,
            "text": full_text,
            "word_count": len(full_text.split()),
            "scraped_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        print(f"  ✗ PDF extraction failed: {e}")
        return None


# ============================================================
# Main Scraper
# ============================================================

def scrape():
    """Main scraping function"""
    
    # Load existing data
    results = load_json(OUT_FILE, [])
    pdf_results = load_json(PDF_FILE, [])
    cache = load_json(CACHE_FILE, {})
    
    done_urls = {r["url"] for r in results}
    done_pdfs = {r["url"] for r in pdf_results}
    
    visited = set()
    queue = [clean_url(BASE)]
    failed = []
    all_pdf_links = set()
    
    print("=" * 60)
    print("DarGlobal Scraper - Improved Version")
    print("=" * 60)
    print(f"Max pages: {MAX_PAGES}")
    print(f"Output: {OUT_FILE}")
    print(f"PDFs: {PDF_FILE}")
    print("=" * 60)
    
    with sync_playwright() as p:
        # Launch persistent context (keeps cookies)
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1366, "height": 850},
            locale="en-GB",
            timezone_id="Europe/London",
        )
        
        page = ctx.new_page()
        
        try:
            # Scrape webpages
            while queue and len(visited) < MAX_PAGES:
                url = queue.pop(0)
                
                if url in visited:
                    continue
                
                visited.add(url)
                print(f"\n[{len(visited)}/{MAX_PAGES}] {url}")
                
                # Skip if already scraped
                if url in done_urls and url in cache:
                    print("  ✓ Already scraped (cached)")
                    links = set(cache[url].get("links", []))
                    pdfs = set(cache[url].get("pdfs", []))
                else:
                    # Fetch page
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
                        page.wait_for_timeout(random.randint(2000, 4000))
                        html = page.content()
                        
                        # Check if blocked
                        if looks_blocked(html):
                            print("  ⚠ Challenge detected, waiting...")
                            page.wait_for_timeout(8000)
                            html = page.content()
                            
                            if looks_blocked(html):
                                print("  ✗ Still blocked, skipping")
                                failed.append(url)
                                continue
                        
                        # Extract content
                        data = extract_text(html, url)
                        
                        # Extract links
                        links = get_links(html, url)
                        pdfs = get_pdf_links(html, url)
                        
                        # Cache for future runs
                        cache[url] = {
                            "links": sorted(links),
                            "pdfs": sorted(pdfs)
                        }
                        save_json(CACHE_FILE, cache)
                        
                        # Save if has meaningful content
                        if len(data["text"]) > 100:
                            results.append(data)
                            done_urls.add(url)
                            save_json(OUT_FILE, results)
                            print(f"  ✓ Saved ({data['word_count']} words)")
                        else:
                            print(f"  ⚠ Too little content ({len(data['text'])} chars)")
                        
                        # Collect PDF links
                        all_pdf_links.update(pdfs)
                        if pdfs:
                            print(f"  📄 Found {len(pdfs)} PDF link(s)")
                        
                        time.sleep(random.uniform(1.5, 3.0))
                    
                    except PWTimeout:
                        print("  ✗ Timeout")
                        failed.append(url)
                        continue
                    
                    except Exception as e:
                        print(f"  ✗ Error: {e}")
                        failed.append(url)
                        continue
                
                # Add discovered links to queue
                for link in links:
                    if link not in visited and link not in queue:
                        queue.append(link)
            
            # Process PDFs
            if all_pdf_links:
                print("\n" + "=" * 60)
                print(f"Processing {len(all_pdf_links)} PDF(s)")
                print("=" * 60)
                
                for pdf_url in sorted(all_pdf_links):
                    if pdf_url in done_pdfs:
                        print(f"\n✓ Already extracted: {pdf_url}")
                        continue
                    
                    pdf_data = extract_pdf_content(pdf_url, ctx, page)  # Pass page object
                    
                    if pdf_data:
                        pdf_results.append(pdf_data)
                        done_pdfs.add(pdf_url)
                        save_json(PDF_FILE, pdf_results)
                    
                    time.sleep(random.uniform(1.0, 2.0))
        
        except KeyboardInterrupt:
            print("\n\n⚠ Interrupted by user. Progress saved.")
        
        finally:
            ctx.close()
    
    # Save failed URLs
    if failed:
        FAILED_FILE.write_text("\n".join(failed), encoding="utf-8")
    
    # Summary
    print("\n" + "=" * 60)
    print("Scraping Complete!")
    print("=" * 60)
    print(f"Webpages: {len(results)} saved to {OUT_FILE}")
    print(f"PDFs: {len(pdf_results)} saved to {PDF_FILE}")
    print(f"Failed: {len(failed)} URLs")
    
    if results:
        # Handle both old and new data formats
        total_words = sum(r.get("word_count", len(r.get("text", "").split())) for r in results)
        print(f"Total words (webpages): {total_words:,}")
    
    if pdf_results:
        total_pdf_words = sum(r.get("word_count", 0) for r in pdf_results)
        print(f"Total words (PDFs): {total_pdf_words:,}")
    
    print("=" * 60)


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    scrape()
