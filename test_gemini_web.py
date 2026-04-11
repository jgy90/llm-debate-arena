"""Use Whale browser (already logged in) with remote debugging."""
import asyncio
import subprocess
import time
from playwright.async_api import async_playwright

WHALE_PATH = "/Applications/Whale.app/Contents/MacOS/Whale"
DEBUG_PORT = 9222

async def main():
    subprocess.run(["pkill", "-f", "Whale"], capture_output=True)
    time.sleep(2)

    # Launch Whale with debug port using DEFAULT profile (already logged in)
    chrome_proc = subprocess.Popen([
        WHALE_PATH,
        f"--remote-debugging-port={DEBUG_PORT}",
        "--no-first-run",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("Whale 시작 중... 5초 대기")
    time.sleep(5)

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
        context = browser.contexts[0]
        page = context.pages[0]

        print("gemini.google.com 으로 이동...")
        resp = await page.goto("https://gemini.google.com/app", wait_until="networkidle", timeout=30000)
        print(f"Status: {resp.status}")
        await asyncio.sleep(3)

        url = page.url
        title = await page.title()
        print(f"URL: {url}")
        print(f"Title: {title}")

        if "signin" in url or "accounts.google" in url:
            print("\n❌ 로그인 필요. Whale에서 Google 로그인 후 다시 실행하세요.")
            print("Enter로 종료...")
            await asyncio.to_thread(input)
            chrome_proc.terminate()
            return

        if resp.status == 502:
            print("\n❌ 502 에러. Enter로 종료...")
            await asyncio.to_thread(input)
            chrome_proc.terminate()
            return

        # Find input elements
        print("\n=== Input elements ===")
        els = await page.query_selector_all(
            "textarea, [contenteditable='true'], div[role='textbox'], "
            "p[data-placeholder], .ql-editor, rich-textarea, "
            "[aria-label*='prompt'], [aria-label*='메시지'], [aria-label*='입력']"
        )
        for i, el in enumerate(els):
            tag = await el.evaluate("e => e.tagName")
            cls = (await el.get_attribute("class") or "")[:80]
            aria = await el.get_attribute("aria-label") or ""
            role = await el.get_attribute("role") or ""
            ce = await el.get_attribute("contenteditable") or ""
            print(f"  [{i}] <{tag}> role='{role}' ce='{ce}' aria='{aria}' class='{cls}'")

        print("\n=== Buttons with aria-label ===")
        buttons = await page.query_selector_all("button[aria-label]")
        for i, btn in enumerate(buttons):
            aria = await btn.get_attribute("aria-label") or ""
            visible = await btn.is_visible()
            if visible:
                print(f"  [{i}] aria='{aria}'")

        print("\n=== Page text (first 500 chars) ===")
        text = await page.inner_text("body")
        print(text[:500])

        print("\nEnter를 누르면 종료...")
        await asyncio.to_thread(input)
        chrome_proc.terminate()

asyncio.run(main())
