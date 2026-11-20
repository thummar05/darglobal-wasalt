from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)
    
    # Listen to console and response events
    page.on("console", lambda msg: print("PAGE CONSOLE:", msg.text))
    page.on("response", lambda r: print(f"RESP: {r.status} {r.url[:70]}"))
    
    print("Navigating...")
    page.goto("https://www.darglobal.co.uk/", wait_until="commit", timeout=20000)
    
    print("Waiting for framenavigated event...")
    try:
        page.wait_for_event("framenavigated", timeout=15000)
        print("Frame navigated! Current URL:", page.url)
    except Exception as e:
        print("Wait for event error:", e)
        
    try:
        page.wait_for_load_state("load", timeout=10000)
    except Exception:
        pass
        
    print("Current URL:", page.url)
    print("Title:", page.title())
    try:
        content = page.content()
        print("Content length:", len(content))
        print("Snippet:", content[:500])
    except Exception as e:
        print("Content error:", e)
        
    browser.close()
