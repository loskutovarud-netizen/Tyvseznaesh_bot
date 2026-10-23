import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiohttp import web
import os

# Импортируем твои настройки и вопросы
from config import BOT_TOKEN
from questions import QUESTIONS
from results import RESULTS

# Настройка логов
logging.basicConfig(level=logging.INFO)

# --- МИКРО-СЕРВЕР ДЛЯ RENDER ---
async def handle(request):
    return web.Response(text="Бот запущен и работает!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render дает порт в переменной окружения PORT
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# --- ЛОГИКА БОТА ---
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(f"Привет, {message.from_user.full_name}! Тест готов к запуску. Напиши что-нибудь, чтобы начать.")

# Сюда можно добавить остальную логику из предыдущих сообщений 
# (обработку вопросов и результатов), если она была в этом же файле.

async def main():
    bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
    
    # Запускаем веб-сервер в фоне
    asyncio.create_task(start_web_server())
    
    logging.info("🤖 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
