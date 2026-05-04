"""
Browser MCP Server
==================
FastMCP server exposing browser automation tools via browser-use + Playwright.
browser-use wraps Playwright internally — no direct Playwright imports needed here.

Run with:
    ./venv/bin/python browser_mcp_server.py

Tools (call in this order for any browser task):
    1. browser_navigate       → open a URL
    2. browser_get_state      → get numbered interactive elements
    3. browser_click          → click element by index number
    4. browser_input          → type into input field by index number
    5. browser_screenshot     → capture viewport as base64 PNG
    6. browser_press_key      → press keyboard key (Enter, Tab, Escape …)
    7. browser_scroll         → scroll page up or down
    8. browser_wait           → wait for page to fully load
    9. browser_extract_content→ read visible text content of page
   10. browser_close          → close browser and free resources
"""

import os
import sys

# Resolve imports from mcp_client_side root
sys.path.insert(0, os.path.dirname(__file__))

from fastmcp import FastMCP

from core.agents.browser_session import (
    _navigate,
    _get_state,
    _click,
    _input,
    _press_key,
    _scroll,
    _wait_for_load,
    _extract_content,
    _screenshot,
    _close_browser,
)

mcp = FastMCP("BrowserAgent")


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def browser_navigate(url: str) -> dict:
    """Navigate the browser to a URL.
    Always call this first to open a page before any interaction.
    Returns the page title and a screenshot confirming the page loaded."""
    return await _navigate(url)


@mcp.tool()
async def browser_get_state(url: str = "") -> dict:
    """Get the current page state: a numbered list of ALL interactive elements
    (inputs, buttons, links, checkboxes, selects).
    ALWAYS call this before clicking or typing — use the 'index' numbers
    returned here with browser_click and browser_input.
    Never invent CSS selectors. If url is provided and differs from the current
    page, navigates there first."""
    return await _get_state(url)


@mcp.tool()
async def browser_click(index: int) -> dict:
    """Click an interactive element by its index number from the most recent
    browser_get_state call.
    Use for: buttons, links, checkboxes, radio buttons, form submission.
    Returns a screenshot after clicking so you can confirm the result.
    Call browser_get_state again if the page changed since the last state dump."""
    return await _click(int(index))


@mcp.tool()
async def browser_input(index: int, value: str, press_enter: bool = False) -> dict:
    """Type text into an input field identified by its index from browser_get_state.
    Use for: text fields, email fields, search boxes, textareas.
    Set press_enter=True to submit via Enter key instead of clicking a button.
    Returns a screenshot after typing."""
    return await _input(int(index), str(value), bool(press_enter))


@mcp.tool()
async def browser_screenshot(url: str = "") -> dict:
    """Capture a PNG screenshot of the current browser viewport and return it
    as a base64 string.
    Call after every significant action (navigate, click, fill) to visually
    confirm what happened on the page."""
    return await _screenshot(url)


@mcp.tool()
async def browser_press_key(key: str) -> dict:
    """Press a keyboard key on the currently focused element.
    Valid keys: Enter, Tab, Escape, ArrowDown, ArrowUp, ArrowLeft, ArrowRight,
    Backspace, Delete, PageDown, PageUp, Home, End.
    Use to: submit forms without a button, dismiss modals, navigate dropdowns."""
    return await _press_key(str(key))


@mcp.tool()
async def browser_scroll(direction: str = "down", pixels: int = 600) -> dict:
    """Scroll the current page up or down.
    direction: 'up' or 'down'
    pixels: distance to scroll (default 600)
    After scrolling, call browser_get_state again — indices refresh for
    newly visible elements."""
    return await _scroll(str(direction), int(pixels))


@mcp.tool()
async def browser_wait(timeout_ms: int = 10000) -> dict:
    """Wait until the current page reaches network idle (no requests for 500ms).
    Call this after async actions like clicking a tab, submitting a search,
    or triggering a dynamic load — before calling browser_get_state again."""
    return await _wait_for_load(int(timeout_ms))


@mcp.tool()
async def browser_extract_content(url: str = "", max_chars: int = 4000) -> dict:
    """Extract the visible plain-text content of the current page.
    Use to: read page content, verify what's displayed, check results,
    or extract values shown on screen.
    max_chars limits the returned text (default 4000)."""
    return await _extract_content(url, int(max_chars))


@mcp.tool()
async def browser_close() -> dict:
    """Close the browser session and free all resources.
    Call when all browser tasks for the current conversation are complete."""
    return await _close_browser()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
