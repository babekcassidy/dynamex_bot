import asyncio
import os
import re

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

from scraper import DynamexScraper

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN .env faylında yoxdur")

TRACKING_REGEX = re.compile(r"^[A-Za-z0-9_-]{5,40}$")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

scraper = DynamexScraper()
request_lock = asyncio.Lock()


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Salam. Tracking ID göndərin, mən sizə Çəki və Borc məlumatını çıxarım."
    )


@dp.message(F.text)
async def tracking_handler(message: Message):
    tracking_id = message.text.strip()

    if not TRACKING_REGEX.match(tracking_id):
        await message.answer("Düzgün tracking ID göndərin.")
        return

    status_message = await message.answer("Sorğu qəbul edildi. Yoxlanılır...")

    try:
        async with request_lock:
            result = await scraper.get_weight_and_debt(tracking_id)

        if result is None:
            await status_message.edit_text("Bu tracking ID üzrə məlumat tapılmadı.")
            return

        reply_text = (
            f"Tracking ID: {result['tracking_id']}\n"
            f"Çəki: {result['weight']}\n"
            f"Borc: {result['debt']}"
        )

        await status_message.edit_text(reply_text)

    except Exception as e:
        await status_message.edit_text(f"Xəta baş verdi: {e}")


async def main():
    await scraper.start()
    try:
        await dp.start_polling(bot)
    finally:
        await scraper.stop()


if __name__ == "__main__":
    asyncio.run(main())