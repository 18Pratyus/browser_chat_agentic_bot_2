"""
Browser Session — new browser-use API (BrowserSession / BrowserProfile / event bus).
"""

import asyncio
import base64
import os
import threading
from typing import Optional


# ── Sync → async bridge ───────────────────────────────────────────────────────

class _LoopThread:
    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

    def start(self):
        if self._loop is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="BrowserUseLoop")
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def submit(self, coro, timeout: float = 120.0):
        self.start()
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)


_LOOP = _LoopThread()


def run_async(coro, timeout: float = 120.0) -> dict:
    try:
        return _LOOP.submit(coro, timeout=timeout)
    except Exception as e:
        return {"status": "failed", "error": f"Browser loop error: {e}"}


# ── Singleton browser session ─────────────────────────────────────────────────

class _Session:
    def __init__(self):
        self._session = None

    async def _ensure(self):
        if self._session is not None:
            return
        from browser_use.browser.session import BrowserSession
        from browser_use.browser.profile import BrowserProfile

        headless = os.environ.get("BROWSER_HEADLESS", "true").lower() != "false"
        profile = BrowserProfile(headless=headless)
        self._session = BrowserSession(browser_profile=profile)
        await self._session.start()
        print(f"[BrowserSession] Started  headless={headless}")

    async def get(self):
        await self._ensure()
        return self._session

    async def close(self):
        if self._session is not None:
            try:
                await self._session.stop()
            except Exception:
                pass
            finally:
                self._session = None


SESSION = _Session()


# ── Element helper ────────────────────────────────────────────────────────────

def _el_summary(node) -> dict:
    attrs = getattr(node, "attributes", {}) or {}
    tag = getattr(node, "tag_name", "")
    text_fn = getattr(node, "get_all_text_till_next_clickable_element", None)
    text = ""
    if callable(text_fn):
        try:
            text = str(text_fn()).strip()[:80]
        except Exception:
            pass
    label = (
        attrs.get("aria-label", "")
        or attrs.get("placeholder", "")
        or attrs.get("name", "")
        or attrs.get("id", "")
    )
    el_type = attrs.get("type", "")
    name_id = (attrs.get("name", "") + attrs.get("id", "")).lower()
    return {
        "index": getattr(node, "highlight_index", None),
        "tag": tag,
        "type": el_type,
        "text": text,
        "label": str(label)[:80],
        "name": attrs.get("name", ""),
        "id": attrs.get("id", ""),
        "placeholder": attrs.get("placeholder", ""),
        "href": attrs.get("href", ""),
        "is_input": tag in ("input", "textarea", "select"),
        "is_password": el_type == "password" or "password" in name_id,
    }


# ── Screenshot helper ─────────────────────────────────────────────────────────

async def _screenshot_b64() -> str:
    session = await SESSION.get()
    try:
        png_bytes = await session.take_screenshot()
        return base64.b64encode(png_bytes).decode("utf-8")
    except Exception:
        return ""


# ── Core async functions ──────────────────────────────────────────────────────

async def _navigate(url: str) -> dict:
    if not url:
        return {"status": "failed", "error": "Empty URL"}
    session = await SESSION.get()
    try:
        await session.navigate_to(url)
    except Exception as e:
        return {"status": "failed", "error": str(e)}
    current_url = await session.get_current_page_url()
    title = await session.get_current_page_title()
    screenshot_b64 = await _screenshot_b64()
    return {
        "status": "success",
        "url": current_url,
        "title": title,
        "screenshot_b64": screenshot_b64,
    }


async def _get_state(url: str = "") -> dict:
    session = await SESSION.get()
    if url:
        try:
            await session.navigate_to(url)
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    await session.get_browser_state_summary()
    selector_map = await session.get_selector_map()

    elements = []
    for idx, node in sorted(selector_map.items()):
        el = _el_summary(node)
        el["index"] = int(idx)
        elements.append(el)

    current_url = await session.get_current_page_url()
    title = await session.get_current_page_title()

    page = await session.get_current_page()
    headings = []
    if page:
        try:
            headings = await page.evaluate(
                "() => Array.from(document.querySelectorAll('h1,h2,h3'))"
                ".map(h => h.textContent.trim()).filter(t => t).slice(0, 10)"
            )
        except Exception:
            pass

    inputs = [e for e in elements if e.get("is_input")]
    buttons = [e for e in elements if not e.get("is_input")]

    return {
        "status": "success",
        "url": current_url,
        "title": title,
        "headings": headings,
        "inputs": inputs,
        "buttons": buttons[:30],
        "total_elements": len(elements),
        "guidance": (
            "Use the 'index' values from inputs/buttons with browser_click "
            "and browser_input. Do NOT invent CSS selectors."
        ),
    }


async def _click(index: int) -> dict:
    from browser_use.browser.events import ClickElementEvent

    session = await SESSION.get()
    node = await session.get_element_by_index(index)
    if node is None:
        return {
            "status": "failed",
            "error": f"Index {index} not found. Call browser_get_state first.",
        }

    prev_url = await session.get_current_page_url()
    try:
        event = session.event_bus.dispatch(ClickElementEvent(node=node))
        await event
        await event.event_result(raise_if_any=True, raise_if_none=False)
    except Exception as e:
        return {"status": "failed", "error": f"Click failed: {e}"}

    current_url = await session.get_current_page_url()
    screenshot_b64 = await _screenshot_b64()
    return {
        "status": "success",
        "index": index,
        "element": _el_summary(node),
        "prev_url": prev_url,
        "current_url": current_url,
        "navigated": prev_url != current_url,
        "screenshot_b64": screenshot_b64,
    }


async def _input(index: int, value: str, press_enter: bool = False) -> dict:
    from browser_use.browser.events import TypeTextEvent, SendKeysEvent

    session = await SESSION.get()
    node = await session.get_element_by_index(index)
    if node is None:
        return {
            "status": "failed",
            "error": f"Index {index} not found. Call browser_get_state first.",
        }

    try:
        event = session.event_bus.dispatch(TypeTextEvent(node=node, text=value, clear=True))
        await event
        await event.event_result(raise_if_any=True, raise_if_none=False)

        if press_enter:
            key_event = session.event_bus.dispatch(SendKeysEvent(keys="Enter"))
            await key_event
            await key_event.event_result(raise_if_any=True, raise_if_none=False)
    except Exception as e:
        return {"status": "failed", "error": f"Input failed: {e}"}

    summary = _el_summary(node)
    current_url = await session.get_current_page_url()
    screenshot_b64 = await _screenshot_b64()
    return {
        "status": "success",
        "index": index,
        "element": summary,
        "value_set": "[hidden — password]" if summary.get("is_password") else value,
        "current_url": current_url,
        "screenshot_b64": screenshot_b64,
    }


async def _press_key(key: str) -> dict:
    from browser_use.browser.events import SendKeysEvent

    session = await SESSION.get()
    try:
        event = session.event_bus.dispatch(SendKeysEvent(keys=key))
        await event
        await event.event_result(raise_if_any=True, raise_if_none=False)
    except Exception as e:
        return {"status": "failed", "error": str(e)}

    current_url = await session.get_current_page_url()
    screenshot_b64 = await _screenshot_b64()
    return {
        "status": "success",
        "key": key,
        "current_url": current_url,
        "screenshot_b64": screenshot_b64,
    }


async def _scroll(direction: str, pixels: int) -> dict:
    from browser_use.browser.events import ScrollEvent

    session = await SESSION.get()
    try:
        event = session.event_bus.dispatch(
            ScrollEvent(direction=direction, amount=pixels, node=None)
        )
        await event
        await event.event_result(raise_if_any=True, raise_if_none=False)
    except Exception as e:
        # fallback: raw JS scroll
        try:
            page = await session.get_current_page()
            dy = pixels if direction == "down" else -pixels
            await page.evaluate(f"window.scrollBy(0, {dy})")
        except Exception:
            return {"status": "failed", "error": str(e)}

    current_url = await session.get_current_page_url()
    screenshot_b64 = await _screenshot_b64()
    return {
        "status": "success",
        "direction": direction,
        "pixels": pixels,
        "current_url": current_url,
        "screenshot_b64": screenshot_b64,
    }


async def _wait_for_load(timeout_ms: int) -> dict:
    session = await SESSION.get()
    page = await session.get_current_page()
    if page is None:
        return {"status": "failed", "error": "No active page"}
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass
    current_url = await session.get_current_page_url()
    return {"status": "success", "current_url": current_url}


async def _extract_content(url: str = "", max_chars: int = 4000) -> dict:
    session = await SESSION.get()
    if url:
        try:
            await session.navigate_to(url)
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    page = await session.get_current_page()
    if page is None:
        return {"status": "failed", "error": "No active page"}

    try:
        text = await page.evaluate(
            "() => document.body.innerText || document.body.textContent || ''"
        )
    except Exception as e:
        return {"status": "failed", "error": str(e)}

    current_url = await session.get_current_page_url()
    title = await session.get_current_page_title()
    return {
        "status": "success",
        "url": current_url,
        "title": title,
        "content": text[:max_chars],
        "truncated": len(text) > max_chars,
        "total_chars": len(text),
    }


async def _screenshot(url: str = "") -> dict:
    session = await SESSION.get()
    if url:
        try:
            await session.navigate_to(url)
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    current_url = await session.get_current_page_url()
    title = await session.get_current_page_title()
    b64 = await _screenshot_b64()
    return {
        "status": "success",
        "current_url": current_url,
        "title": title,
        "screenshot_b64": b64,
    }


async def _close_browser() -> dict:
    await SESSION.close()
    return {"status": "success", "message": "Browser session closed."}
