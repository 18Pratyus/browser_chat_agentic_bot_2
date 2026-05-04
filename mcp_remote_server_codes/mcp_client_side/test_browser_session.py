import asyncio, sys
sys.path.insert(0, '.')
from core.agents.browser_session import _navigate, _get_state, _screenshot, _close_browser

async def test():
    print('--- navigate ---')
    r = await _navigate('https://example.com')
    print('status:', r['status'], 'title:', r.get('title'), 'screenshot bytes:', len(r.get('screenshot_b64', '')))

    print('--- get_state ---')
    r = await _get_state()
    print('status:', r['status'], 'elements:', r.get('total_elements'))

    print('--- close ---')
    r = await _close_browser()
    print(r)

asyncio.run(test())
