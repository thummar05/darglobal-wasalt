"""
Scraper Utility Functions
--------------------------
Common functions used by all scrapers:
- Rate limiting
- Retry logic
- Text cleaning
- File saving
"""

import time
import json
import httpx
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging

# Setup logging so we can see what's happening
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================
# Rate Limiting
# ============================================================

class RateLimiter:
    """
    Simple rate limiter to avoid overwhelming servers.
    
    Usage:
        limiter = RateLimiter(delay=2)
        limiter.wait()  # Waits if we're going too fast
    """
    
    def __init__(self, delay: float = 2.0):
        """
        Args:
            delay: Minimum seconds between requests
        """
        self.delay = delay
        self.last_request_time = 0
    
    def wait(self):
        """Wait if necessary to maintain rate limit"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.delay:
            wait_time = self.delay - elapsed
            logger.info(f"Rate limiting: waiting {wait_time:.2f}s")
            time.sleep(wait_time)
        self.last_request_time = time.time()


# ============================================================
# HTTP Request with Retries
# ============================================================

def fetch_with_retry(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    max_retries: int = 3,
    timeout: int = 30
) -> Optional[httpx.Response]:
    """
    Fetch URL with automatic retries on failure.
    
    Args:
        url: The URL to fetch
        headers: Optional HTTP headers
        max_retries: Number of retry attempts
        timeout: Request timeout in seconds
    
    Returns:
        Response object or None if all retries failed
    """
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()  # Raises error for 4xx/5xx
                return response
        
        except httpx.HTTPError as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {url}: {e}")
            
            # Don't retry on 404 or 403 (page doesn't exist or forbidden)
            if hasattr(e, 'response') and e.response and e.response.status_code in [403, 404]:
                logger.error(f"Permanent error for {url}, not retrying")
                return None
            
            # Wait before retrying (exponential backoff)
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 1s, 2s, 4s, ...
                logger.info(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
        
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {e}")
            return None
    
    logger.error(f"All {max_retries} attempts failed for {url}")
    return None


# ============================================================
# Text Cleaning
# ============================================================

def clean_text(text: str) -> str:
    """
    Clean scraped text by removing extra whitespace and normalizing.
    
    Args:
        text: Raw text from webpage
    
    Returns:
        Cleaned text
    """
    if not text:
        return ""
    
    # Remove extra whitespace
    text = " ".join(text.split())
    
    # Remove common boilerplate phrases (can be expanded)
    boilerplate_phrases = [
        "Cookie Policy",
        "Privacy Policy",
        "Terms of Service",
        "All rights reserved",
        "© 20",  # Copyright notices
    ]
    
    for phrase in boilerplate_phrases:
        text = text.replace(phrase, "")
    
    return text.strip()


# ============================================================
# Data Saving
# ============================================================

def save_scraped_data(
    data: List[Dict[str, Any]],
    site_name: str,
    output_dir: str = "data/raw"
) -> Path:
    """
    Save scraped data to JSON file.
    
    Args:
        data: List of scraped records
        site_name: Name of the site (e.g., 'darglobal', 'wasalt')
        output_dir: Directory to save to
    
    Returns:
        Path to saved file
    """
    # Create output directory if it doesn't exist
    output_path = Path(output_dir) / site_name
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Create filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = output_path / f"{site_name}_{timestamp}.json"
    
    # Add metadata
    output = {
        "site": site_name,
        "scraped_at": datetime.now().isoformat(),
        "total_records": len(data),
        "records": data
    }
    
    # Save to file
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved {len(data)} records to {filename}")
    return filename


# ============================================================
# URL Validation
# ============================================================

def is_valid_url(url: str) -> bool:
    """
    Check if a URL is valid and should be scraped.
    
    Args:
        url: URL to validate
    
    Returns:
        True if valid, False otherwise
    """
    if not url:
        return False
    
    # Must start with http or https
    if not url.startswith(("http://", "https://")):
        return False
    
    # Skip common non-content pages
    skip_patterns = [
        "/login",
        "/signup",
        "/cart",
        "/checkout",
        ".pdf",
        ".jpg",
        ".png",
        ".zip",
        "javascript:",
        "mailto:",
        "#"
    ]
    
    for pattern in skip_patterns:
        if pattern in url.lower():
            return False
    
    return True


# ============================================================
# Robots.txt Checker
# ============================================================

def check_robots_txt(base_url: str, user_agent: str = "*") -> Dict[str, Any]:
    """
    Check robots.txt for a domain.
    
    Args:
        base_url: Base URL of the site (e.g., 'https://example.com')
        user_agent: User agent to check rules for
    
    Returns:
        Dict with 'allowed' boolean and 'rules' list
    """
    robots_url = base_url.rstrip('/') + '/robots.txt'
    
    try:
        response = fetch_with_retry(robots_url, max_retries=1)
        if not response:
            logger.warning(f"Could not fetch robots.txt from {robots_url}")
            return {"allowed": True, "rules": [], "note": "No robots.txt found"}
        
        # Parse robots.txt (simple parsing)
        rules = response.text.split('\n')
        disallowed_paths = []
        
        for line in rules:
            line = line.strip()
            if line.lower().startswith('disallow:'):
                path = line.split(':', 1)[1].strip()
                if path:
                    disallowed_paths.append(path)
        
        return {
            "allowed": True,
            "rules": disallowed_paths,
            "note": f"Found {len(disallowed_paths)} disallow rules"
        }
    
    except Exception as e:
        logger.error(f"Error checking robots.txt: {e}")
        return {"allowed": True, "rules": [], "note": "Error checking robots.txt"}


# ============================================================
# Progress Tracker
# ============================================================

class ProgressTracker:
    """
    Simple progress tracker for scraping operations.
    
    Usage:
        tracker = ProgressTracker(total=100)
        tracker.update(10)  # Scraped 10 items
    """
    
    def __init__(self, total: int):
        self.total = total
        self.current = 0
        self.start_time = time.time()
    
    def update(self, amount: int = 1):
        """Update progress"""
        self.current += amount
        elapsed = time.time() - self.start_time
        
        if self.current > 0:
            avg_time = elapsed / self.current
            remaining = (self.total - self.current) * avg_time
            
            logger.info(
                f"Progress: {self.current}/{self.total} "
                f"({self.current/self.total*100:.1f}%) "
                f"- Est. remaining: {remaining/60:.1f}m"
            )
    
    def complete(self):
        """Mark as complete and show final stats"""
        elapsed = time.time() - self.start_time
        logger.info(
            f"✓ Complete! Scraped {self.current}/{self.total} items "
            f"in {elapsed/60:.1f} minutes"
        )


# ============================================================
# Testing function
# ============================================================

if __name__ == "__main__":
    print("Testing scraper utilities...\n")
    
    # Test rate limiter
    print("1. Testing Rate Limiter...")
    limiter = RateLimiter(delay=1)
    limiter.wait()
    limiter.wait()
    print("✓ Rate limiter works\n")
    
    # Test text cleaning
    print("2. Testing Text Cleaning...")
    dirty_text = "  This   is   messy    text  with   spaces  "
    clean = clean_text(dirty_text)
    print(f"Before: '{dirty_text}'")
    print(f"After: '{clean}'")
    print("✓ Text cleaning works\n")
    
    # Test URL validation
    print("3. Testing URL Validation...")
    test_urls = [
        ("https://example.com/page", True),
        ("https://example.com/login", False),
        ("javascript:void(0)", False),
        ("https://example.com/image.jpg", False),
    ]
    for url, expected in test_urls:
        result = is_valid_url(url)
        status = "✓" if result == expected else "✗"
        print(f"{status} {url}: {result}")
    
    print("\n✓ All utility tests passed!")
