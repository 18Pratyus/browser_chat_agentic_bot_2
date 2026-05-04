# agents/retest_agent/tools/zap_browser_tools.py
# Dynamic Browser Interaction — powered by browser-use library.
#
# WHY browser-use:
#   browser-use wraps Playwright's async API and adds an element-indexing
#   system. Every interactive element on the current page is assigned a
#   highlight_index (0, 1, 2 …). The LLM picks an element by NUMBER, not by
#   inventing a CSS selector — so selector hallucination is structurally
#   impossible.
#
# THREADING MODEL:
#   browser-use requires an async event loop. LangGraph runs tools on sync
#   worker threads. We keep ONE dedicated daemon asyncio loop thread; every
#   @tool wrapper dispatches its coroutine there via run_coroutine_threadsafe.
#   This permanently eliminates the greenlet "cannot switch threads" crash.
#
# ─────────────────────────────────────────────────────────────────────────
# TOOLS
# ─────────────────────────────────────────────────────────────────────────
#   INDEX-BASED (preferred — no selector hallucination):
#     zap_browser_state          → get numbered interactive elements on page
#     zap_click_by_index         → click element #N
#     zap_input_by_index         → fill element #N with text
#     zap_press_key              → keyboard: Enter / Tab / Escape etc.
#     zap_scroll_page            → scroll viewport up or down
#     zap_wait_for_load          → wait for network idle
#     zap_extract_page_content   → dump visible text (verify XSS reflection)
#     zap_get_page_screenshot    → PNG screenshot as base64
#
#   LEGACY (backwards compat — selector-based):
#     zap_get_page_dom           → DOM dump (calls zap_browser_state internally)
#     zap_click_element          → click by CSS selector / text
#     zap_fill_any_field         → fill by CSS selector
#
#   HUMAN / VISION:
#     zap_ask_human_input        → pause & wait for operator (CAPTCHA / OTP)
#     zap_analyze_screenshot_with_llm → vision LLM describes a screenshot

import asyncio
import base64
import os
import threading
import time
import uuid
from typing import Optional

from langchain_core.tools import tool
from mcp_connections.zap_client import SESSION_STATE


# ── Background asyncio event loop ─────────────────────────────────────────────

class _LoopThread:
    """One daemon thread running an asyncio loop — all browser calls go here."""

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

    def start(self):
        if self._loop is not None:
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="BrowserUseLoop"
        )
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


def _run(coro, timeout: float = 120.0) -> dict:
    try:
        return _LOOP.submit(coro, timeout=timeout)
    except Exception as e:
        return {"status": "failed", "error": f"Browser loop error: {e}"}


# ── Persistent browser-use session ────────────────────────────────────────────

class _BrowserUseSession:
    """
    Wraps browser-use Browser + BrowserContext as a persistent singleton.
    The same context (with cookies, history, form state) is reused across
    every tool call in a retest run.
    """

    def __init__(self):
        self._browser = None
        self._context = None   # browser_use BrowserContext
        self._page    = None   # underlying Playwright Page (via get_current_page)

    async def _ensure(self):
        # Check BOTH — if new_context() failed before, _browser is set but _context is None
        if self._browser is not None and self._context is not None:
            return

        from browser_use import Browser, BrowserConfig
        from browser_use.browser.context import BrowserContextConfig

        headless = os.environ.get("DISPLAY") is None

        if self._browser is None:
            zap_proxy = os.environ.get("ZAP_PROXY_HOST", "127.0.0.1")
            zap_port  = os.environ.get("ZAP_PROXY_PORT", "8888")
            self._browser = Browser(
                config=BrowserConfig(
                    headless=headless,
                    disable_security=True,
                    proxy={"server": f"http://{zap_proxy}:{zap_port}"},
                    extra_chromium_args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--ignore-certificate-errors",
                    ],
                )
            )

        if self._context is None:
            try:
                # Try with BrowserContextConfig first
                self._context = await self._browser.new_context(
                    config=BrowserContextConfig()
                )
            except TypeError:
                # Some versions don't accept config kwarg
                self._context = await self._browser.new_context()

        print(
            f"[BrowserUse] ✅  Started (headless={headless}, "
            f"DISPLAY={os.environ.get('DISPLAY','not set')})"
        )

    async def context(self):
        await self._ensure()
        return self._context

    async def page(self):
        """Return the underlying Playwright Page object."""
        ctx = await self.context()
        return await ctx.get_current_page()

    async def navigate(self, url: str):
        """Navigate to url if not already there."""
        if not url:
            return
        page = await self.page()
        if page.url.rstrip("/") == url.rstrip("/"):
            return
        # Inject SESSION_STATE cookies before navigating
        if SESSION_STATE.cookies:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            cookies = [
                {"name": k, "value": v, "domain": parsed.netloc, "path": "/"}
                for k, v in SESSION_STATE.cookies.items()
            ]
            try:
                await page.context.add_cookies(cookies)
            except Exception:
                pass
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass

    async def sync_cookies(self):
        """Pull browser cookies back into SESSION_STATE."""
        try:
            page = await self.page()
            raw = await page.context.cookies()
            SESSION_STATE.cookies.update({c["name"]: c["value"] for c in raw})
        except Exception:
            pass

    async def close(self):
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        finally:
            self._browser = None
            self._context = None
            self._page    = None


SESSION = _BrowserUseSession()


# ── Human input store ─────────────────────────────────────────────────────────

_PENDING: dict = {}
_ANSWERS: dict = {}
_INPUT_LOCK = threading.Lock()


def get_pending_question() -> Optional[dict]:
    with _INPUT_LOCK:
        for qid, data in _PENDING.items():
            if data["status"] == "waiting":
                return {
                    "question_id": qid,
                    "question":    data["question"],
                    "fields":      data.get("fields", []),
                }
    return None


def submit_answer(question_id: str, answer: str) -> bool:
    with _INPUT_LOCK:
        if question_id in _PENDING:
            _ANSWERS[question_id] = answer
            _PENDING[question_id]["status"] = "answered"
            return True
    return False


# ── Async core implementations ────────────────────────────────────────────────

def _element_summary(el) -> dict:
    """Convert a browser-use DOMElementNode to a JSON-safe summary dict."""
    attrs = getattr(el, "attributes", {}) or {}
    tag   = getattr(el, "tag_name", "")
    text  = (getattr(el, "get_all_text_till_next_clickable_element", None) or
             (lambda: ""))()
    if callable(text):
        text = ""
    text = str(text).strip()[:80] if text else ""
    label     = attrs.get("aria-label", "") or attrs.get("placeholder", "") or \
                attrs.get("name", "") or attrs.get("id", "")
    el_type   = attrs.get("type", "")
    is_input  = tag in ("input", "textarea", "select")
    is_pw     = el_type == "password" or "password" in (attrs.get("name","") + attrs.get("id","")).lower()
    idx       = getattr(el, "highlight_index", None)
    return {
        "index":      idx,
        "tag":        tag,
        "type":       el_type,
        "text":       text,
        "label":      str(label)[:80],
        "name":       attrs.get("name", ""),
        "id":         attrs.get("id", ""),
        "placeholder":attrs.get("placeholder", ""),
        "is_input":   is_input,
        "is_password":is_pw,
    }


async def _browser_state(url: str) -> dict:
    print(f"\n[DEBUG][zap_browser_state] called with url='{url}'")
    await SESSION.navigate(url)
    ctx   = await SESSION.context()
    state = await ctx.get_state()

    page  = await SESSION.page()
    title = await page.title()
    print(f"[DEBUG][zap_browser_state] current_url='{page.url}' title='{title}'")

    selector_map = getattr(state, "selector_map", {}) or {}
    print(f"[DEBUG][zap_browser_state] selector_map has {len(selector_map)} elements")
    elements = []
    for idx, node in sorted(selector_map.items()):
        summary = _element_summary(node)
        summary["index"] = int(idx)
        elements.append(summary)
        print(f"[DEBUG][zap_browser_state]   [{idx}] tag={summary['tag']} type={summary['type']} label='{summary['label']}' name='{summary['name']}' id='{summary['id']}'")

    inputs  = [e for e in elements if e.get("is_input")]
    buttons = [e for e in elements if not e.get("is_input")]
    print(f"[DEBUG][zap_browser_state] inputs={[e['index'] for e in inputs]} buttons={[e['index'] for e in buttons]}")

    # CAPTCHA detection (lightweight — just checks page HTML)
    html_content = await page.content()
    captcha = {
        "recaptcha_v2":  "g-recaptcha" in html_content or "recaptcha/api.js" in html_content,
        "recaptcha_v3":  "grecaptcha.execute" in html_content,
        "hcaptcha":      "h-captcha" in html_content or "hcaptcha.com" in html_content,
        "cloudflare":    "cf-turnstile" in html_content or "challenges.cloudflare.com" in html_content,
        "image_captcha": bool(await page.query_selector('img[src*="captcha" i]')),
    }
    captcha_present = any(captcha.values())

    headings = await page.evaluate(
        "() => Array.from(document.querySelectorAll('h1,h2,h3'))"
        ".map(h=>h.textContent.trim()).filter(t=>t).slice(0,10)"
    )

    return {
        "status":           "success",
        "url":              state.url or page.url,
        "title":            title,
        "headings":         headings,
        "elements":         elements,
        "inputs":           inputs,
        "buttons":          buttons[:30],
        "total_elements":   len(elements),
        "captcha_detected": captcha_present,
        "captcha_details":  captcha,
        "guidance": (
            "⚠️  CAPTCHA detected — call zap_ask_human_input() before proceeding."
            if captcha_present else
            "✅  Use `index` values from `inputs` / `buttons` arrays with "
            "zap_click_by_index and zap_input_by_index. Do NOT invent selectors."
        ),
    }


async def _take_page_screenshot(page) -> str:
    """Take a screenshot of the current page and return base64 string."""
    try:
        ctx = await SESSION.context()
        return await ctx.take_screenshot(full_page=False)
    except Exception:
        try:
            png = await page.screenshot(full_page=False, type="png")
            return base64.b64encode(png).decode("utf-8")
        except Exception:
            return ""


async def _click_by_index(index: int) -> dict:
    print(f"\n[DEBUG][zap_click_by_index] called with index={index}")
    ctx   = await SESSION.context()
    page  = await SESSION.page()
    print(f"[DEBUG][zap_click_by_index] current_url='{page.url}'")
    state = await ctx.get_state()
    selector_map = getattr(state, "selector_map", {}) or {}
    print(f"[DEBUG][zap_click_by_index] selector_map keys={sorted(selector_map.keys())}")

    node = selector_map.get(index)
    if node is None:
        print(f"[DEBUG][zap_click_by_index] ❌ index {index} NOT in selector_map!")
        return {
            "status": "failed",
            "error":  f"Index {index} not found on current page. "
                      "Call zap_browser_state first to get current indices.",
        }

    print(f"[DEBUG][zap_click_by_index] found node: tag={getattr(node,'tag_name','?')} attrs={getattr(node,'attributes',{})}")
    prev_url = page.url

    # Force all target=_blank links to open in same tab so ZAP captures them
    try:
        await page.evaluate("() => document.querySelectorAll('a[target]').forEach(a => a.removeAttribute('target'))")
        print(f"[DEBUG][zap_click_by_index] removed target=_blank from all links")
    except Exception:
        pass

    # Register dialog handler BEFORE click — capture message only, do NOT accept here.
    # browser-use's internal handler will accept the dialog; we just record the evidence.
    dialog_info: dict = {}

    async def _on_dialog(dialog):
        try:
            dialog_info["message"] = dialog.message
            dialog_info["type"]    = dialog.type
            print(f"[DEBUG][zap_click_by_index] 🚨 dialog fired: type={dialog.type} msg='{dialog.message}'")
        except Exception:
            pass
        # Do NOT call dialog.accept() here — let browser-use's handler do it

    page.on("dialog", _on_dialog)

    try:
        await ctx._click_element_node(node)
        print(f"[DEBUG][zap_click_by_index] ✅ click succeeded")
    except Exception as e:
        print(f"[DEBUG][zap_click_by_index] ❌ click failed: {e}")
        try:
            page.remove_listener("dialog", _on_dialog)
        except Exception:
            pass
        return {"status": "failed", "error": f"Click failed: {e}"}

    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass

    try:
        page.remove_listener("dialog", _on_dialog)
    except Exception:
        pass

    await SESSION.sync_cookies()
    current_url = page.url
    print(f"[DEBUG][zap_click_by_index] after click url='{current_url}' navigated={prev_url != current_url}")

    screenshot_b64 = await _take_page_screenshot(page)

    return {
        "status":          "success",
        "index":           index,
        "element":         _element_summary(node),
        "prev_url":        prev_url,
        "current_url":     current_url,
        "navigated":       prev_url != current_url,
        "new_tab":         False,
        "screenshot_b64":  screenshot_b64,
        "dialog_captured": dialog_info if dialog_info else None,
    }


async def _input_by_index(index: int, value: str, press_enter: bool = False) -> dict:
    print(f"\n[DEBUG][zap_input_by_index] called with index={index} value='{value}' press_enter={press_enter}")
    ctx   = await SESSION.context()
    page  = await SESSION.page()
    print(f"[DEBUG][zap_input_by_index] current_url='{page.url}'")
    state = await ctx.get_state()
    selector_map = getattr(state, "selector_map", {}) or {}
    print(f"[DEBUG][zap_input_by_index] selector_map keys={sorted(selector_map.keys())}")

    node = selector_map.get(index)
    if node is None:
        print(f"[DEBUG][zap_input_by_index] ❌ index {index} NOT in selector_map!")
        return {
            "status": "failed",
            "error":  f"Index {index} not found on current page. "
                      "Call zap_browser_state first to get current indices.",
        }

    print(f"[DEBUG][zap_input_by_index] found node: tag={getattr(node,'tag_name','?')} attrs={getattr(node,'attributes',{})}")
    try:
        await ctx._input_text_element_node(node, value)
        print(f"[DEBUG][zap_input_by_index] ✅ input succeeded — typed '{value}'")
        if press_enter:
            await page.keyboard.press("Enter")
            print(f"[DEBUG][zap_input_by_index] pressed Enter")
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
    except Exception as e:
        print(f"[DEBUG][zap_input_by_index] ❌ input failed: {e}")
        return {"status": "failed", "error": f"Input failed: {e}"}

    summary = _element_summary(node)
    is_pw   = summary.get("is_password", False)

    screenshot_b64 = await _take_page_screenshot(page)

    return {
        "status":         "success",
        "index":          index,
        "element":        summary,
        "value_set":      "[hidden — password]" if is_pw else value,
        "current_url":    page.url,
        "screenshot_b64": screenshot_b64,
    }


async def _press_key(key: str) -> dict:
    page = await SESSION.page()
    try:
        await page.keyboard.press(key)
        try:
            await page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass
        return {"status": "success", "key": key, "current_url": page.url}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


async def _scroll(direction: str, pixels: int) -> dict:
    page = await SESSION.page()
    try:
        dy = pixels if direction == "down" else -pixels
        await page.evaluate(f"window.scrollBy(0, {dy})")
        return {"status": "success", "direction": direction, "pixels": pixels, "current_url": page.url}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


async def _wait_for_load(timeout_ms: int) -> dict:
    page = await SESSION.page()
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        return {"status": "success", "current_url": page.url}
    except Exception as e:
        return {"status": "failed", "error": str(e), "current_url": page.url}


async def _extract_content(url: str, max_chars: int) -> dict:
    await SESSION.navigate(url)
    page = await SESSION.page()
    try:
        text = await page.evaluate(
            "() => document.body.innerText || document.body.textContent || ''"
        )
        return {
            "status":      "success",
            "url":         page.url,
            "title":       await page.title(),
            "content":     text[:max_chars],
            "truncated":   len(text) > max_chars,
            "total_chars": len(text),
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


async def _screenshot(url: str) -> dict:
    if url:
        await SESSION.navigate(url)
    ctx   = await SESSION.context()
    page  = await SESSION.page()
    try:
        # Use browser-use's take_screenshot if available (returns base64 str)
        b64 = await ctx.take_screenshot(full_page=False)
    except Exception:
        # Fallback: raw playwright screenshot
        png = await page.screenshot(full_page=False, type="png")
        b64 = base64.b64encode(png).decode("utf-8")
    return {
        "status":         "success",
        "current_url":    page.url,
        "title":          await page.title(),
        "screenshot_b64": b64,
    }


# ── Legacy selector-based helpers ─────────────────────────────────────────────

async def _click_selector(selector: str, page_url: str) -> dict:
    await SESSION.navigate(page_url)
    page     = await SESSION.page()
    prev_url = page.url
    last_err = ""
    for strat in [
        lambda: page.locator(selector).first.click(timeout=5000),
        lambda: page.get_by_text(selector, exact=False).first.click(timeout=5000),
        lambda: page.get_by_role("button", name=selector).first.click(timeout=5000),
        lambda: page.get_by_role("link",   name=selector).first.click(timeout=5000),
        lambda: page.get_by_label(selector).first.click(timeout=5000),
    ]:
        try:
            await strat()
            try:
                await page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:
                pass
            await SESSION.sync_cookies()
            return {
                "status":      "success",
                "selector":    selector,
                "prev_url":    prev_url,
                "current_url": page.url,
                "navigated":   prev_url != page.url,
            }
        except Exception as e:
            last_err = str(e)
    return {
        "status": "failed",
        "error":  f"Could not click '{selector}'. Last: {last_err}",
        "tip":    "Prefer zap_browser_state + zap_click_by_index.",
    }


async def _fill_selector(selector: str, value: str, page_url: str) -> dict:
    await SESSION.navigate(page_url)
    page = await SESSION.page()
    try:
        loc = page.locator(selector)
        if await loc.count() == 0:
            return {
                "status": "failed",
                "error":  f"No element for selector '{selector}'",
                "tip":    "Prefer zap_browser_state + zap_input_by_index.",
            }
        first = loc.first
        await first.fill("")
        await first.fill(value)
        is_pw = "password" in selector.lower() or (await first.get_attribute("type") == "password")
        return {
            "status":      "success",
            "selector":    selector,
            "value_set":   "[hidden — password]" if is_pw else value,
            "current_url": page.url,
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


# ── @tool wrappers ────────────────────────────────────────────────────────────

@tool
def zap_browser_state(url: str = "") -> dict:
    """Get the current page state: a numbered list of every interactive element (inputs, buttons, links, checkboxes). ALWAYS call this FIRST before interacting with any page. Each element has an `index` field. Use those index numbers with zap_click_by_index and zap_input_by_index — never invent CSS selectors. If `url` is provided and differs from the current page, the browser navigates there first."""
    return _run(_browser_state(url or ""))


@tool
def zap_click_by_index(index: int) -> dict:
    """Click the interactive element identified by its `index` number from the most recent zap_browser_state call. This is the correct way to click buttons, submit forms, follow links, and toggle checkboxes. The index maps to a real DOM element so it cannot miss. Call zap_browser_state again if the page has changed since the last state dump."""
    return _run(_click_by_index(int(index)))


@tool
def zap_input_by_index(index: int, value: str, press_enter: bool = False) -> dict:
    """Type `value` into the input/textarea/select identified by its `index` from the most recent zap_browser_state call. Use for email, password, username, OTP, search queries, XSS payloads, and any other text field. Set press_enter=True to submit via Enter key instead of clicking a button."""
    return _run(_input_by_index(int(index), str(value), bool(press_enter)))


@tool
def zap_press_key(key: str) -> dict:
    """Press a keyboard key on the currently focused element. Valid values: Enter, Tab, Escape, ArrowDown, ArrowUp, Backspace, PageDown, PageUp. Use to submit forms without a button, dismiss modals, or advance wizard steps."""
    return _run(_press_key(str(key)))


@tool
def zap_scroll_page(direction: str = "down", pixels: int = 600) -> dict:
    """Scroll the current page. `direction` must be 'up' or 'down', `pixels` is the scroll distance. Use when the element you need is not visible in the current viewport. After scrolling, call zap_browser_state again to refresh indices for newly-visible elements."""
    return _run(_scroll(str(direction), int(pixels)))


@tool
def zap_wait_for_load(timeout_ms: int = 10000) -> dict:
    """Wait until the current page reaches network idle (no requests for 500 ms) or until timeout_ms elapses. Call this after async actions like clicking a tab, submitting a search, or triggering a dynamic load before calling zap_browser_state again."""
    return _run(_wait_for_load(int(timeout_ms)))


@tool
def zap_extract_page_content(url: str = "", max_chars: int = 4000) -> dict:
    """Return the plain visible text content of the current page. Use this to verify whether an XSS payload was reflected, read error messages, confirm success banners, or extract parameter values shown on screen. Much lighter than a full DOM dump."""
    return _run(_extract_content(url or "", int(max_chars)))


@tool
def zap_get_page_screenshot(url: str = "") -> dict:
    """Capture a PNG screenshot of the current browser viewport and return it as base64. Call after every significant action (fill, click, navigate) to visually confirm the result. The screenshot is also sent to the frontend so the operator can see what the agent is doing."""
    return _run(_screenshot(url or ""))


# ── Legacy backwards-compat tools ─────────────────────────────────────────────

@tool
def zap_get_page_dom(url: str) -> dict:
    """Legacy DOM inspector — kept for backwards compatibility with older plans. Internally calls zap_browser_state. Prefer zap_browser_state for new plans because it exposes a clean `index` for every element."""
    if not url:
        return {"status": "failed", "error": "url is required"}
    state = _run(_browser_state(url))
    if state.get("status") != "success":
        return state
    inputs  = [{**e, "best_selector": f"[data-index='{e['index']}']", "value": "[hidden]" if e.get("is_password") else ""} for e in state.get("inputs", [])]
    buttons = [{**e, "best_selector": f"[data-index='{e['index']}']"} for e in state.get("buttons", [])]
    return {
        "status":           "success",
        "url":              state.get("url"),
        "title":            state.get("title"),
        "headings":         state.get("headings", []),
        "inputs":           inputs,
        "buttons":          buttons,
        "forms":            [],
        "total_inputs":     len(inputs),
        "total_forms":      0,
        "captcha_detected": state.get("captcha_detected", False),
        "captcha_details":  state.get("captcha_details", {}),
        "guidance":         state.get("guidance", ""),
    }


@tool
def zap_click_element(selector: str, page_url: str = "") -> dict:
    """Legacy selector-based click — kept for backwards compatibility. Tries CSS selector, text match, ARIA role, then label in order. Prefer zap_click_by_index for reliability."""
    if not selector:
        return {"status": "failed", "error": "selector is required"}
    return _run(_click_selector(selector, page_url or ""))


@tool
def zap_fill_any_field(selector: str, value: str, page_url: str = "") -> dict:
    """Legacy selector-based fill — kept for backwards compatibility. Prefer zap_input_by_index for reliability."""
    if not selector:
        return {"status": "failed", "error": "selector is required"}
    return _run(_fill_selector(selector, value, page_url or ""))


# ── Human-in-the-loop ─────────────────────────────────────────────────────────

@tool
def zap_ask_human_input(question: str, fields: list = None) -> str:
    """Pause the retest agent and ask the human operator for input. MUST be used for: login forms (pass fields=[{label,index}] list), CAPTCHA solutions, OTP/SMS codes, 2FA tokens. Blocks until operator responds via the dashboard (timeout: 5 minutes). For login, returns JSON string like {"Username":"admin","Password":"secret"}. For CAPTCHA, returns raw answer string."""
    question_id = uuid.uuid4().hex[:8]
    with _INPUT_LOCK:
        _PENDING[question_id] = {"question": question, "status": "waiting", "fields": fields or []}

    print(f"\n{'='*60}")
    print(f"[RETEST AGENT] 🛑  Human input required")
    print(f"[RETEST AGENT] ID:       {question_id}")
    print(f"[RETEST AGENT] Question: {question}")
    print(f"[RETEST AGENT] Submit:   POST /retest/submit-input")
    print(f"{'='*60}\n")

    timeout = 0
    while timeout < 300:
        with _INPUT_LOCK:
            if question_id in _ANSWERS:
                answer = _ANSWERS.pop(question_id)
                _PENDING.pop(question_id, None)
                print(f"[RETEST AGENT] ✅  Answer received for {question_id}")
                return answer
        time.sleep(2)
        timeout += 2

    with _INPUT_LOCK:
        _PENDING.pop(question_id, None)
    return f"TIMEOUT — No human input received within 5 minutes for: {question}"


@tool
def zap_analyze_screenshot_with_llm(image_b64: str, question: str) -> dict:
    """Send a base64-encoded screenshot to the vision LLM with a specific question. Use to read CAPTCHA text, understand complex page layouts, analyse Burp Suite screenshots from the pentest report, or extract parameter values visible only in an image."""
    try:
        from core.ollama_client import get_remediation_llm
        from langchain_core.messages import HumanMessage

        if image_b64.startswith("/9j/"):
            mime = "image/jpeg"
        elif image_b64.startswith("R0lGO"):
            mime = "image/gif"
        else:
            mime = "image/png"

        content = [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
        ]
        llm      = get_remediation_llm(temperature=0.1)
        response = llm.invoke([HumanMessage(content=content)])
        return {"status": "success", "question": question, "analysis": response.content}
    except Exception as e:
        return {"status": "failed", "error": str(e)}