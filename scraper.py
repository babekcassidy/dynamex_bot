import os
import re
from typing import Optional, Dict

from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv()

LOGIN_URL = os.getenv("LOGIN_URL", "").strip()
PANEL_USERNAME = os.getenv("PANEL_USERNAME", "").strip()
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "").strip()
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60000"))


class DynamexScraper:
    def __init__(self) -> None:
        self.playwright = None
        self.browser = None

    async def start(self) -> None:
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=HEADLESS,
            slow_mo=300
        )

    async def stop(self) -> None:
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def get_weight_and_debt(self, tracking_id: str) -> Optional[Dict[str, str]]:
        if not self.browser:
            raise RuntimeError("Browser start edilməyib")

        context = await self.browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(REQUEST_TIMEOUT)

        try:
            # Login page
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")
            await page.wait_for_selector("#adminloginform-username", state="visible")
            await page.fill("#adminloginform-username", PANEL_USERNAME)
            await page.fill("#adminloginform-password", PANEL_PASSWORD)
            await page.click('button[name="login-button"]')
            await page.wait_for_timeout(2500)

            # Əgər login alınmayıbsa
            if await page.locator("#adminloginform-username").count() > 0:
                await page.screenshot(path="debug_login_failed.png", full_page=True)
                raise RuntimeError("Login alınmadı. debug_login_failed.png faylına bax.")

            # Bağlamalar > Bütün bağlamalar
            await page.wait_for_selector('a.dropdown-toggle:has-text("Bağlamalar")', state="visible")
            await page.click('a.dropdown-toggle:has-text("Bağlamalar")')
            await page.wait_for_timeout(1000)

            await page.wait_for_selector('a.btn-icon:has-text("Bütün bağlamalar")', state="visible")
            await page.click('a.btn-icon:has-text("Bütün bağlamalar")')
            await page.wait_for_timeout(2500)

            # Tracking ID input - filter sətrindəki ikinci input
            input_locator = page.locator("input[placeholder='Tracking ID']").last
            await input_locator.wait_for(state="visible")

            await input_locator.click()
            await page.wait_for_timeout(300)

            await input_locator.fill("")
            await page.wait_for_timeout(200)

            await input_locator.type(tracking_id, delay=100)
            await page.wait_for_timeout(500)

            current_value = await input_locator.input_value()
            if current_value.strip() != tracking_id:
                await page.evaluate(
                    """(value) => {
                        const elements = document.querySelectorAll("table input[name='ParcelSearch[tracking_id]']");
                        const el = elements[1];
                        if (el) {
                            el.focus();
                            el.value = value;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'Enter' }));
                        }
                    }""",
                    tracking_id
                )
                await page.wait_for_timeout(500)

            current_value = await input_locator.input_value()
            if current_value.strip() != tracking_id:
                await page.screenshot(path="debug_tracking_not_filled.png", full_page=True)
                raise RuntimeError(
                    f"Tracking ID input-a yazılmadı. Hazırki dəyər: '{current_value}'. "
                    "debug_tracking_not_filled.png faylına bax."
                )

            # Axtarış düyməsi
            search_button = page.locator("button.btn.btn-default").filter(has_text="Axtarış").last
            await search_button.wait_for(state="visible")
            await search_button.click()
            await page.wait_for_timeout(3000)

            await page.screenshot(path="debug_after_search.png", full_page=True)

            # Table nəticələri
            rows = page.locator("table tbody tr")
            row_count = await rows.count()

            if row_count == 0:
                raise RuntimeError("Cədvəldə heç bir nəticə yoxdur. debug_after_search.png faylına bax.")

            found_row = None
            for i in range(row_count):
                row = rows.nth(i)
                row_text = (await row.inner_text()).strip()
                if tracking_id.lower() in row_text.lower():
                    found_row = row
                    break

            if found_row is None and row_count == 1:
                only_row = rows.nth(0)
                only_row_text = (await only_row.inner_text()).strip()
                if only_row_text and "Məlumat tapılmadı" not in only_row_text:
                    found_row = only_row

            if found_row is None:
                all_rows = await rows.all_inner_texts()
                raise RuntimeError(f"Nəticə sətri tapılmadı. Rows: {all_rows}")

            td_values = await found_row.locator("td").all_inner_texts()
            td_values = [x.strip() for x in td_values if x.strip()]

            weight = self._extract_weight(td_values)
            debt = self._extract_debt(td_values)

            if weight is None and debt is None:
                raise RuntimeError(f"Çəki və Borc tapılmadı. TD values: {td_values}")

            return {
                "tracking_id": tracking_id,
                "weight": weight or "Tapılmadı",
                "debt": debt or "Tapılmadı",
            }

        except PlaywrightTimeoutError:
            await page.screenshot(path="debug_timeout.png", full_page=True)
            raise RuntimeError("Element tapılmadı və ya sayt gec cavab verdi. debug_timeout.png faylına bax.")
        finally:
            await context.close()

    def _extract_weight(self, td_values: list[str]) -> Optional[str]:
        for value in td_values:
            if "kq" in value.lower():
                return value
        return None

    def _extract_debt(self, td_values: list[str]) -> Optional[str]:
        money_pattern = re.compile(r"[$₼]")
        zero_pattern = re.compile(r"^0([.,]0+)?$")

        for value in td_values:
            cleaned = value.strip()

            if money_pattern.search(cleaned):
                return cleaned

            if zero_pattern.match(cleaned):
                return cleaned

        return None