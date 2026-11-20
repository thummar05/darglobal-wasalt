"""
Wasalt Scraper (Optimized)
---------------------------
Wasalt is a Next.js site that embeds structured data in __NEXT_DATA__ JSON blocks.
This scraper extracts data directly from these JSON blocks and HTML pages,
normalizes content, and saves individual records to the specified output directory.

Usage:
    python scrapers/wasalt.py --output-dir data/raw/wasalt --max-pages 50
"""

import warnings
warnings.filterwarnings("ignore")

import os
import sys
import json
import re
import logging
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

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
        save_scraped_data,
        save_raw_record,
        is_valid_url,
        check_robots_txt,
        ProgressTracker,
        logger
    )
except ImportError:
    from utils import (
        ScrapedDocument,
        RateLimiter,
        fetch_with_retry,
        clean_text,
        save_scraped_data,
        save_raw_record,
        is_valid_url,
        check_robots_txt,
        ProgressTracker,
        logger
    )

# ============================================================
# Configuration
# ============================================================

BASE_URL = "https://wasalt.sa/en"
SITE_NAME = "wasalt"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "wasalt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Referer": "https://wasalt.sa/"
}


# ============================================================
# Next.js Data Extraction
# ============================================================

def extract_nextjs_data(html: str) -> Optional[Dict[str, Any]]:
    """
    Extract __NEXT_DATA__ JSON block from Next.js page.
    
    Args:
        html: Page HTML
    
    Returns:
        Parsed JSON data or None
    """
    try:
        soup = BeautifulSoup(html, 'lxml')
        next_data_script = soup.find('script', id='__NEXT_DATA__')
        
        if not next_data_script or not next_data_script.string:
            logger.warning("No __NEXT_DATA__ found")
            return None
        
        data = json.loads(next_data_script.string)
        return data
        
    except Exception as e:
        logger.error(f"Error parsing __NEXT_DATA__: {e}")
        return None


def extract_page_props(next_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract pageProps from __NEXT_DATA__.
    
    Args:
        next_data: Parsed __NEXT_DATA__ JSON
    
    Returns:
        Page props dictionary
    """
    if not isinstance(next_data, dict):
        return {}
    try:
        return next_data.get('props', {}).get('pageProps', {})
    except Exception as e:
        logger.debug(f"Error getting pageProps: {e}")
        return {}


# ============================================================
# Page Discovery
# ============================================================

def discover_pages(max_pages: int = 100) -> List[str]:
    """
    Discover pages to scrape from Wasalt website.
    
    Args:
        max_pages: Maximum pages to discover
    
    Returns:
        List of URLs
    """
    logger.info(f"Discovering pages from {BASE_URL}...")
    
    # Priority pages to scrape
    pages = [
        f"{BASE_URL}",  # Homepage
        f"{BASE_URL}/about",
        f"{BASE_URL}/about-us",
        f"{BASE_URL}/services",
        
        # Property listings
        f"{BASE_URL}/properties-for-sale-in-riyadh",
        f"{BASE_URL}/properties-for-rent-in-riyadh",
        f"{BASE_URL}/properties-for-sale-in-jeddah",
        f"{BASE_URL}/properties-for-rent-in-jeddah",
        f"{BASE_URL}/properties-for-sale-in-dammam",
        f"{BASE_URL}/properties-for-sale-in-makkah",
        f"{BASE_URL}/properties-for-sale-in-madinah",
        
        # Property types
        f"{BASE_URL}/villas-for-sale-in-riyadh",
        f"{BASE_URL}/apartments-for-rent-in-riyadh",
        f"{BASE_URL}/lands-for-sale-in-riyadh",
        f"{BASE_URL}/villas-for-sale-in-jeddah",
        f"{BASE_URL}/apartments-for-rent-in-jeddah",
        
        # Search pages
        f"{BASE_URL}/sale/search?propertyFor=sale&countryId=1&type=residential",
        f"{BASE_URL}/rent/search?propertyFor=rent&countryId=1&type=residential",
    ]
    
    discovered_urls = set(pages)
    
    # Scrape homepage to find more links
    try:
        response = fetch_with_retry(BASE_URL, headers=HEADERS)
        if response:
            soup = BeautifulSoup(response.text, 'lxml')
            for link in soup.find_all('a', href=True):
                href = link['href'].strip()
                if href.startswith('/en/'):
                    href = 'https://wasalt.sa' + href
                elif href.startswith('/'):
                    href = BASE_URL + href
                
                if href.startswith('https://wasalt.sa/en') and is_valid_url(href):
                    if not any(x in href for x in ['business.wasalt', 'auction.wasalt']):
                        discovered_urls.add(href)
                        if len(discovered_urls) >= max_pages:
                            break
    except Exception as e:
        logger.error(f"Error discovering pages: {e}")
    
    urls = list(discovered_urls)[:max_pages]
    logger.info(f"Found {len(urls)} pages to scrape")
    return urls


# ============================================================
# Content Extraction
# ============================================================

def identify_page_type(url: str, page_props: Dict[str, Any]) -> str:
    """Identify page type from URL and data."""
    url_lower = url.lower()
    
    if any(p in url_lower for p in ['/properties-for-sale', '/villas-for-sale', '/apartments-for-sale', '/lands-for-sale']):
        return 'property_listing_sale'
    elif any(p in url_lower for p in ['/properties-for-rent', '/apartments-for-rent']):
        return 'property_listing_rent'
    elif '/sale/search' in url_lower:
        return 'search_sale'
    elif '/rent/search' in url_lower:
        return 'search_rent'
    elif 'about' in url_lower:
        return 'about'
    elif 'service' in url_lower:
        return 'service'
    elif page_props.get('cmsData'):
        return 'homepage'
    
    return 'general'


def extract_structured_data(page_props: Dict[str, Any], page_type: str) -> Dict[str, Any]:
    """Extract structured data from page props."""
    data: Dict[str, Any] = {}
    if not isinstance(page_props, dict):
        return data
        
    try:
        if 'cmsData' in page_props:
            cms = page_props['cmsData']
            data['cms_sections'] = {
                'hero': cms.get('section_1_HeroSection', {}),
                'property_types': cms.get('section_3_propertyTypes', []),
                'about': cms.get('section_4_aboutUs', {}),
            }
        
        if 'propertyList' in page_props:
            properties = page_props['propertyList']
            data['properties'] = properties
            data['property_count'] = len(properties) if isinstance(properties, list) else 0
        
        if 'propertyDetails' in page_props:
            data['property_details'] = page_props['propertyDetails']
        
        if 'blogPosts' in page_props:
            data['blog_posts'] = page_props['blogPosts']
        
        if 'menuHeader' in page_props:
            data['navigation'] = page_props['menuHeader']
            
    except Exception as e:
        logger.warning(f"Error extracting structured data: {e}")
    
    return data


def extract_text_content(page_props: Dict[str, Any], soup: BeautifulSoup) -> str:
    """Extract and combine text content from page props and HTML."""
    texts = []
    
    try:
        if isinstance(page_props, dict) and 'cmsData' in page_props:
            cms_str = json.dumps(page_props['cmsData'], ensure_ascii=False)
            cms_texts = re.findall(r'"(?:title|subTitle|heading|content|description)":"([^"]+)"', cms_str)
            texts.extend(cms_texts)
        
        main = soup.find(['main', 'article'])
        if main:
            main_text = main.get_text(separator=' ', strip=True)
            texts.append(main_text)
        elif soup.body:
            texts.append(soup.body.get_text(separator=' ', strip=True))
        
        combined = ' '.join(texts)
        return clean_text(combined)
        
    except Exception as e:
        logger.warning(f"Error extracting text: {e}")
        return ""


def extract_page_content(url: str) -> Optional[ScrapedDocument]:
    """
    Extract content from a Wasalt page and construct a ScrapedDocument.
    """
    try:
        response = fetch_with_retry(url, headers=HEADERS)
        if not response:
            return None
        
        next_data = extract_nextjs_data(response.text)
        page_props = extract_page_props(next_data)
        soup = BeautifulSoup(response.text, 'lxml')
        
        title = soup.title.get_text(strip=True) if soup.title else ""
        if not title and isinstance(page_props, dict):
            meta_title = page_props.get('metaData', {}).get('meta_title') or page_props.get('metaData', {}).get('title_tag')
            title = meta_title or f"Wasalt Real Estate - {url}"
            
        page_type = identify_page_type(url, page_props)
        structured_data = extract_structured_data(page_props, page_type)
        content_text = extract_text_content(page_props, soup)
        
        # Detect city
        city = None
        for c in ["Riyadh", "Jeddah", "Dammam", "Khobar", "Makkah", "Madinah", "Taif", "Al-Oyun"]:
            if c.lower() in url.lower() or c.lower() in title.lower():
                city = c
                break
                
        # Detect property type
        property_type = None
        for pt in ["Villa", "Apartment", "Land", "Floor", "Building", "Duplex"]:
            if pt.lower() in url.lower() or pt.lower() in title.lower():
                property_type = pt
                break
        if not property_type:
            property_type = "Residential" if "residential" in url.lower() else "Commercial" if "commercial" in url.lower() else "General"

        metadata: Dict[str, Any] = {
            "source": "wasalt",
            "url": url,
            "status_code": 200,
            "city": city,
            "property_type": property_type,
            "page_type": page_type,
        }
        
        if structured_data and "properties" in structured_data and structured_data["properties"]:
            first_p = structured_data["properties"][0]
            if isinstance(first_p, dict) and first_p.get("price"):
                metadata["price"] = str(first_p["price"])
                metadata["currency"] = "SAR"
                
        return ScrapedDocument(
            url=url,
            title=clean_text(title) or url,
            site="wasalt",
            page_type=page_type,
            content=clean_text(content_text),
            metadata=metadata
        )
        
    except Exception as e:
        logger.error(f"Error extracting {url}: {e}")
        return None


# ============================================================
# Main Scraping Function
# ============================================================

def scrape_wasalt(
    max_pages: int = 50,
    delay: float = 1.5,
    output_dir: Optional[Union[Path, str]] = None,
    save_batch: bool = False
) -> int:
    """
    Main function to scrape Wasalt website and save individual records.
    
    Args:
        max_pages: Maximum pages to scrape
        delay: Delay between requests
        output_dir: Directory where individual JSON records are saved
        save_batch: If True, also output a single combined batch file
    
    Returns:
        Number of scraped records successfully saved
    """
    logger.info("=" * 60)
    logger.info("Starting Wasalt Scraper")
    logger.info("=" * 60)
    
    if output_dir:
        out_dir = Path(output_dir).resolve()
        if out_dir.name in ("raw", "data"):
            out_dir = out_dir / "wasalt"
    else:
        out_dir = DEFAULT_OUTPUT_DIR
        
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Target Output Directory: {out_dir}")
    
    # Step 1: Robots.txt
    logger.info("\nStep 1: Checking robots.txt...")
    robots_info = check_robots_txt("https://wasalt.sa")
    logger.info(f"Robots.txt: {robots_info['note']}")
    
    # Step 2: Discover
    logger.info("\nStep 2: Discovering pages...")
    urls = discover_pages(max_pages)
    
    if not urls:
        logger.error("No pages found!")
        return 0
    
    # Step 3: Scrape
    logger.info(f"\nStep 3: Scraping up to {len(urls)} pages...")
    logger.info(f"Rate limit: {delay}s between requests")
    
    rate_limiter = RateLimiter(delay=delay)
    progress = ProgressTracker(total=len(urls))
    
    saved_count = 0
    scraped_documents: List[ScrapedDocument] = []
    page_type_counts: Dict[str, int] = {}
    
    for url in urls:
        logger.info(f"\nScraping: {url}")
        rate_limiter.wait()
        
        doc = extract_page_content(url)
        if doc and doc.content:
            saved_file = save_raw_record(site="wasalt", record=doc, output_dir=out_dir)
            saved_count += 1
            scraped_documents.append(doc)
            page_type_counts[doc.page_type] = page_type_counts.get(doc.page_type, 0) + 1
            logger.info(f"✓ Saved ({len(doc.content)} chars, {doc.page_type}): {saved_file.name}")
        else:
            logger.warning("✗ Failed to extract meaningful content")
        
        progress.update()
        if saved_count >= max_pages:
            break
    
    progress.complete()
    
    # Optional Batch File
    if save_batch and scraped_documents:
        batch_dicts = [d.model_dump(exclude_none=True) for d in scraped_documents]
        batch_path = save_scraped_data(batch_dicts, SITE_NAME, output_dir=out_dir)
        logger.info(f"✓ Also saved batch file to: {batch_path}")
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Wasalt Scraping Summary")
    logger.info("=" * 60)
    logger.info(f"Scraped & Saved: {saved_count} records to {out_dir}")
    logger.info("\nPage types breakdown:")
    for pt, c in page_type_counts.items():
        logger.info(f"  - {pt}: {c}")
    logger.info("=" * 60)
    
    return saved_count


def main():
    parser = argparse.ArgumentParser(description="Scrape Wasalt real estate website")
    parser.add_argument("--output-dir", "-o", type=str, default=None, help="Output directory path (default: data/raw/wasalt)")
    parser.add_argument("--max-pages", "-m", type=int, default=50, help="Max pages (default: 50)")
    parser.add_argument("--delay", "-d", type=float, default=1.5, help="Delay in seconds (default: 1.5)")
    parser.add_argument("--save-batch", action="store_true", help="Also save a combined JSON batch file")
    
    args = parser.parse_args()
    
    try:
        count = scrape_wasalt(
            max_pages=args.max_pages,
            delay=args.delay,
            output_dir=args.output_dir,
            save_batch=args.save_batch
        )
        print(f"\n✓ Successfully scraped and saved {count} records from Wasalt!")
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
