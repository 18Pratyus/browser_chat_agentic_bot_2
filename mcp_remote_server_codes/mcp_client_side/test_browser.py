"""
Browser-use + Playwright quick test (new API: BrowserSession/BrowserProfile).

Run with:
    ./browser_env/bin/python test_browser.py
"""

import asyncio
import os


async def main():
    print("=" * 50)
    print("Browser-use + Playwright Test")
    print("=" * 50)

    # ── Test 1: imports ───────────────────────────────
    print("\n[1] Testing imports...")
    try:
        from browser_use.browser.session import BrowserSession
        from browser_use.browser.profile import BrowserProfile
        print("    ✓ browser-use imported OK (new API)")
    except ImportError as e:
        print(f"    ✗ browser-use import FAILED: {e}")
        return

    try:
        import playwright
        print("    ✓ playwright imported OK")
    except ImportError as e:
        print(f"    ✗ playwright import FAILED: {e}")
        return

    # ── Test 2: launch browser ────────────────────────
    print("\n[2] Launching headless Chromium...")
    session = None
    try:
        profile = BrowserProfile(headless=True)
        session = BrowserSession(browser_profile=profile)
        await session.start()
        print("    ✓ BrowserSession started OK")
    except Exception as e:
        print(f"    ✗ BrowserSession start FAILED: {e}")
        return

    # ── Test 3: navigate ──────────────────────────────
    print("\n[3] Navigating to google.com...")
    try:
        await session.navigate_to("https://www.google.com")
        url = await session.get_current_page_url()
        title = await session.get_current_page_title()
        print(f"    ✓ Navigated OK  title='{title}'  url={url}")
    except Exception as e:
        print(f"    ✗ Navigation FAILED: {e}")
        await session.stop()
        return

    # ── Test 4: screenshot ────────────────────────────
    print("\n[4] Taking screenshot...")
    try:
        png_bytes = await session.take_screenshot()  # returns raw bytes
        out_path = os.path.join(os.path.dirname(__file__), "test_screenshot.png")
        with open(out_path, "wb") as f:
            f.write(png_bytes)
        print(f"    ✓ Screenshot saved ({len(png_bytes)} bytes) → {out_path}")
    except Exception as e:
        print(f"    ✗ Screenshot FAILED: {e}")

    # ── Test 5: page elements ─────────────────────────
    print("\n[5] Reading page elements via browser-use state...")
    try:
        await session.get_browser_state_summary()  # builds selector map
        selector_map = await session.get_selector_map()
        url = await session.get_current_page_url()
        print(f"    ✓ Got {len(selector_map)} interactive elements  url={url}")
    except Exception as e:
        print(f"    ✗ Get state FAILED: {e}")

    # ── Cleanup ───────────────────────────────────────
    print("\n[6] Closing browser...")
    try:
        await session.stop()
        print("    ✓ Browser closed OK")
    except Exception as e:
        print(f"    ✗ Close FAILED: {e}")

    print("\n" + "=" * 50)
    print("All tests done! Check results above.")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
