"""
Wasalt Scraper (Optimized)
---------------------------
Wasalt is a Next.js site that embeds all data in __NEXT_DATA__ JSON blocks.
This scraper extracts data directly from these JSON blocks - much faster
and more reliable than parsing HTML!

Strategy:
1. Fetch HTML pages
2. Extract __NEXT_DATA__ JSON from each page
3. Parse structured data (properties, cities, etc.)
4. Save to structured format

Usage:
    python scrapers/wasalt_optimized.py --max-pages 50
"""

import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

import httpx
from bs4 import BeautifulSoup
import json
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime

from scrapers.utils import (
    RateLimiter,
    fetch_with_retry,
    clean_text,
    save_scraped_data,
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
        
        # Find __NEXT_DATA__ script tag
        next_data_script = soup.find('script', id='__NEXT_DATA__')
        
        if not next_data_script:
            logger.warning("No __NEXT_DATA__ found")
            return None
        
        # Parse JSON
        data = json.loads(next_data_script.string)
        return data
        
    except Exception as e:
        logger.error(f"Error parsing __NEXT_DATA__: {e}")
        return None


def extract_page_props(next_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract pageProps from __NEXT_DATA__.
    
    Args:
        next_data: Parsed __NEXT_DATA__ JSON
    
    Returns:
        Page props dictionary
    """
    try:
        return next_data.get('props', {}).get('pageProps', {})
    except:
        return {}


# ============================================================
# Page Discovery
# ============================================================

def discover_pages(max_pages: int = 100) -> List[str]:
    """
    Discover pages to scrape from Wasalt website.
    
    Strategy:
    1. Start with main pages
    2. Extract links from __NEXT_DATA__ 
    3. Add property search pages
    4. Add city-specific pages
    
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
            # Extract __NEXT_DATA__
            next_data = extract_nextjs_data(response.text)
            if next_data:
                # Extract URLs from data
                data_str = json.dumps(next_data)
                
                # Look for redirectSlug and link fields
                soup = BeautifulSoup(response.text, 'lxml')
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    
                    # Convert relative to absolute
                    if href.startswith('/en/'):
                        href = 'https://wasalt.sa' + href
                    elif href.startswith('/'):
                        href = BASE_URL + href
                    
                    # Only Wasalt pages
                    if href.startswith('https://wasalt.sa/en') and is_valid_url(href):
                        # Skip business, auction, blog subdomains
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

def extract_page_content(url: str) -> Optional[Dict[str, Any]]:
    """
    Extract content from a Wasalt page.
    
    Args:
        url: Page URL
    
    Returns:
        Dictionary with extracted data
    """
    try:
        # Fetch page
        response = fetch_with_retry(url, headers=HEADERS)
        if not response:
            return None
        
        # Extract __NEXT_DATA__
        next_data = extract_nextjs_data(response.text)
        if not next_data:
            logger.warning(f"No Next.js data from {url}")
            return None
        
        # Get page props
        page_props = extract_page_props(next_data)
        
        # Parse HTML for additional content
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Extract title
        title = soup.title.string if soup.title else ""
        
        # Identify page type
        page_type = identify_page_type(url, page_props)
        
        # Extract structured data based on page type
        structured_data = extract_structured_data(page_props, page_type)
        
        # Extract text content
        content_text = extract_text_content(page_props, soup)
        
        return {
            "url": url,
            "title": clean_text(title),
            "content": content_text,
            "page_type": page_type,
            "structured_data": structured_data,
            "nextjs_data": page_props,  # Include raw data for analysis
            "scraped_at": datetime.now().isoformat(),
            "word_count": len(content_text.split())
        }
        
    except Exception as e:
        logger.error(f"Error extracting {url}: {e}")
        return None


def identify_page_type(url: str, page_props: Dict) -> str:
    """
    Identify page type from URL and data.
    
    Args:
        url: Page URL
        page_props: Page props from __NEXT_DATA__
    
    Returns:
        Page type string
    """
    url_lower = url.lower()
    
    # Check URL patterns
    if '/properties-for-sale' in url_lower or '/villas-for-sale' in url_lower or '/apartments-for-sale' in url_lower or '/lands-for-sale' in url_lower:
        return 'property_listing_sale'
    elif '/properties-for-rent' in url_lower or '/apartments-for-rent' in url_lower:
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


def extract_structured_data(page_props: Dict, page_type: str) -> Dict[str, Any]:
    """
    Extract structured data from page props.
    
    Args:
        page_props: Page props
        page_type: Page type
    
    Returns:
        Structured data dictionary
    """
    data = {}
    
    try:
        # Homepage CMS data
        if 'cmsData' in page_props:
            cms = page_props['cmsData']
            data['cms_sections'] = {
                'hero': cms.get('section_1_HeroSection', {}),
                'property_types': cms.get('section_3_propertyTypes', []),
                'about': cms.get('section_4_aboutUs', {}),
            }
        
        # Property listings
        if 'propertyList' in page_props:
            properties = page_props['propertyList']
            data['properties'] = properties
            data['property_count'] = len(properties) if isinstance(properties, list) else 0
        
        # Property details
        if 'propertyDetails' in page_props:
            data['property_details'] = page_props['propertyDetails']
        
        # Blog posts
        if 'blogPosts' in page_props:
            data['blog_posts'] = page_props['blogPosts']
        
        # Menu/navigation
        if 'menuHeader' in page_props:
            data['navigation'] = page_props['menuHeader']
        
    except Exception as e:
        logger.warning(f"Error extracting structured data: {e}")
    
    return data


def extract_text_content(page_props: Dict, soup: BeautifulSoup) -> str:
    """
    Extract text content from page props and HTML.
    
    Args:
        page_props: Page props
        soup: BeautifulSoup object
    
    Returns:
        Combined text content
    """
    texts = []
    
    try:
        # Extract text from CMS data
        if 'cmsData' in page_props:
            cms_str = json.dumps(page_props['cmsData'], ensure_ascii=False)
            import re
            # Find all text in quotes
            cms_texts = re.findall(r'"(?:title|subTitle|heading|content|description)":"([^"]+)"', cms_str)
            texts.extend(cms_texts)
        
        # Extract from main HTML
        main = soup.find(['main', 'article'])
        if main:
            main_text = main.get_text(separator=' ', strip=True)
            texts.append(main_text)
        
        # Combine and clean
        combined = ' '.join(texts)
        cleaned = clean_text(combined)
        
        return cleaned
        
    except Exception as e:
        logger.warning(f"Error extracting text: {e}")
        return ""


# ============================================================
# Main Scraping Function
# ============================================================

def scrape_wasalt(max_pages: int = 100, delay: float = 2.0) -> List[Dict[str, Any]]:
    """
    Main function to scrape Wasalt website.
    
    Args:
        max_pages: Maximum pages to scrape
        delay: Delay between requests
    
    Returns:
        List of scraped records
    """
    logger.info("=" * 60)
    logger.info("Starting Wasalt Optimized Scraper")
    logger.info("=" * 60)
    
    # Step 1: Robots.txt
    logger.info("\nStep 1: Checking robots.txt...")
    robots_info = check_robots_txt("https://wasalt.sa")
    logger.info(f"Robots.txt: {robots_info['note']}")
    
    # Step 2: Discover
    logger.info("\nStep 2: Discovering pages...")
    urls = discover_pages(max_pages)
    
    if not urls:
        logger.error("No pages found!")
        return []
    
    # Step 3: Scrape
    logger.info(f"\nStep 3: Scraping {len(urls)} pages...")
    logger.info(f"Rate limit: {delay}s between requests")
    
    rate_limiter = RateLimiter(delay=delay)
    progress = ProgressTracker(total=len(urls))
    
    scraped_data = []
    
    for url in urls:
        logger.info(f"\nScraping: {url}")
        
        # Rate limit
        rate_limiter.wait()
        
        # Extract
        content = extract_page_content(url)
        
        if content:
            scraped_data.append(content)
            logger.info(f"✓ Extracted {content['word_count']} words ({content['page_type']})")
        else:
            logger.warning("✗ Failed")
        
        progress.update()
    
    # Step 4: Save
    progress.complete()
    logger.info("\nStep 4: Saving results...")
    
    if scraped_data:
        raw_output_dir = str(PROJECT_ROOT / "data" / "raw")
        output_file = save_scraped_data(scraped_data, SITE_NAME, output_dir=raw_output_dir)
        logger.info(f"✓ Saved to {output_file}")
    else:
        logger.warning("No data scraped!")
    
    # Step 5: Summary
    logger.info("\n" + "=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    logger.info(f"Scraped: {len(scraped_data)} pages")
    logger.info(f"Total words: {sum(d['word_count'] for d in scraped_data)}")
    
    # Count by type
    types = {}
    for item in scraped_data:
        t = item['page_type']
        types[t] = types.get(t, 0) + 1
    
    logger.info("\nPage types:")
    for t, count in types.items():
        logger.info(f"  - {t}: {count}")
    
    logger.info("=" * 60)
    
    return scraped_data


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Scrape Wasalt website (optimized)")
    parser.add_argument("--max-pages", type=int, default=50, help="Max pages (default: 50)")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay in seconds (default: 2.0)")
    
    args = parser.parse_args()
    
    try:
        results = scrape_wasalt(max_pages=args.max_pages, delay=args.delay)
        
        if results:
            print(f"\n✓ Successfully scraped {len(results)} pages from Wasalt!")
        else:
            print("\n✗ Scraping failed.")
            sys.exit(1)
    
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(0)
    
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
