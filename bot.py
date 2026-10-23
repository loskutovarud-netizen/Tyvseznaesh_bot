import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

# Импорт твоих данных
from config import BOT_TOKEN
from questions import QUESTIONS
from results import RESULTS

# Настройка логов
logging.basicConfig(level=logging.INFO)

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (чтобы не падал) ---
async def handle(request):
    return web.Response(text="Бот живой!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"🌐 Веб-сервер запущен на порту {port}")

# --- ЛОГИКА ТЕСТА ---
class TestStates(StatesGroup):
    in_progress = State()

dp = Dispatcher()

# Хранилище ответов (в памяти)
user_data = {}

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_data[user_id] = {
        "scores": {"collector": 0, "analyst": 0, "frozen": 0, "perfectionist": 0, "loner": 0},
        "current_q": 0
    }
    await state.set_state(TestStates.in_progress)
    await send_question(message, 0)

async def send_question(message: Message, q_index: int):
    q = QUESTIONS[q_index]
    total = len(QUESTIONS)
    
    text = f"<b>{q['category']} ({q_index + 1}/{total})</b>\n\n{q['text']}"
    
    buttons = []
    for i, (emoji, ans_text, _) in enumerate(q['answers']):
        buttons.append([InlineKeyboardButton(text=f"{emoji} {ans_text}", callback_data=f"q_{q_index}_{i}")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("q_"))
async def process_answer(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in user_data:
        await callback.answer("Начни тест заново через /start")
        return

    data = callback.data.split("_")
    q_index = int(data[1])
    a_index = int(data[2])
    
    # Считаем баллы
    scores_to_add = QUESTIONS[q_index]['answers'][a_index][2]
    for key, val in scores_to_add.items():
        user_data[user_id]["scores"][key] += val
    
    next_q = q_index + 1
    if next_q < len(QUESTIONS):
        user_data[user_id]["current_q"] = next_q
        await callback.message.edit_reply_markup(reply_markup=None) # Убираем кнопки
        await send_question(callback.message, next_q)
    else:
        await show_result(callback.message, user_id, state)
    
    await callback.answer()

async def show_result(message: Message, user_id: int, state: FSMContext):
    scores = user_data[user_id]["scores"]
    main_type = max(scores, key=scores.get)
    res = RESULTS[main_type]
    
    await message.answer("📊 <b>Тест завершен! Твой результат:</b>")
    await message.answer(res['msg1'])
    await message.answer(res['msg2'])
    await message.answer(res['msg3'])
    await message.answer(res['msg4'])
    
    await state.clear()
    del user_data[user_id]

# --- ЗАПУСК ---
async def main():
    # Исправленный запуск бота для aiogram 3.x
    bot = Bot(
        token=BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode="HTML")
    )
    
    # Сначала запускаем веб-сервер, потом бота
    await start_web_server()
    
    logging.info("🤖 Бот запускает polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен")
