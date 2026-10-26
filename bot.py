import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, 
    LabeledPrice, PreCheckoutQuery
)
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

from config import BOT_TOKEN, PROVIDER_TOKEN, SKIP_PAYMENT
from questions import QUESTIONS
from results import RESULTS

logging.basicConfig(level=logging.INFO)

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

class TestStates(StatesGroup):
    in_progress = State()

dp = Dispatcher()
user_data = {}

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if SKIP_PAYMENT:
        await start_test(message, state)
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ Разобраться и получить план (199 ₽)", callback_data="buy_test")]
    ])
    
    start_text = (
        "🧠 <b>Тест «Где мой тормоз?»</b>\n\n"
        "Ты прочитал кучу книг, посмотрел сотни роликов и идеально знаешь, <i>ЧТО</i> нужно делать. "
        "Но почему-то продолжаешь откладывать жизнь на потом. Знакомо?\n\n"
        "Дело не в лени и не в слабой воле. Твой мозг просто попал в один из 5 подсознательных <b>«паттернов застревания»</b>.\n\n"
        "🎯 <b>Что ты получишь по итогам теста:</b>\n"
        "1️⃣ <b>Точный диагноз:</b> Узнаешь свой главный тип тормоза (Коллекционер, Аналитик, Замороженный, Перфекционист или Одиночка).\n"
        "2️⃣ <b>Разбор механики:</b> Поймёшь, КАК именно твой мозг обманывает тебя и создаёт иллюзию движения.\n"
        "3️⃣ <b>Персональный план:</b> Получишь 5 конкретных микро-шагов, которые сработают именно для твоего психотипа.\n"
        "4️⃣ <b>Инструкция по разморозке:</b> Как начать действовать уже сегодня без насилия над собой.\n\n"
        "⏱ <b>Формат:</b> 18 глубоких вопросов (4 минуты)\n"
        "🚀 <b>Результат:</b> Сразу в чат в удобном формате\n\n"
        "💰 <b>Стоимость доступа:</b> 199 ₽ <i>(вместо разовой консультации психолога за 5 000 ₽)</i>"
    )
    
    await message.answer(start_text, reply_markup=kb)

@dp.callback_query(F.data == "buy_test")
async def send_invoice(callback: types.CallbackQuery):
    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Тест «Где мой тормоз?»",
        description="Разбор паттерна застревания + персональный план из 5 шагов.",
        payload="test_access",
        provider_token=PROVIDER_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(label="Доступ к тесту", amount=19900)]
    )
    await callback.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message, state: FSMContext):
    await message.answer("✅ Оплата прошла успешно! Начинаем тест...")
    await start_test(message, state)

async def start_test(message: Message, state: FSMContext):
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
    letters = ["A", "B", "C", "D"]
    
    text = f"📍 <b>{q['category']} ({q_index + 1}/{total})</b>\n\n"
    text += f"<b>{q['text']}</b>\n\n"
    
    buttons = []
    for i, (emoji, ans_text, _) in enumerate(q['answers']):
        text += f"<b>{letters[i]}.</b> {emoji} {ans_text}\n\n"
        buttons.append(InlineKeyboardButton(text=f"Вариант {letters[i]}", callback_data=f"q_{q_index}_{i}"))
    
    kb_rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("q_"))
async def process_answer(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in user_data:
        await callback.answer("Начни заново через /start")
        return

    data = callback.data.split("_")
    q_index = int(data[1])
    a_index = int(data[2])
    
    scores_to_add = QUESTIONS[q_index]['answers'][a_index][2]
    for key, val in scores_to_add.items():
        user_data[user_id]["scores"][key] += val
    
    next_q = q_index + 1
    if next_q < len(QUESTIONS):
        user_data[user_id]["current_q"] = next_q
        await callback.message.delete()
        await send_question(callback.message, next_q)
    else:
        await callback.message.delete()
        await show_result(callback.message, user_id, state)
    await callback.answer()

async def show_result(message: Message, user_id: int, state: FSMContext):
    scores = user_data[user_id]["scores"]
    main_type = max(scores, key=scores.get)
    res = RESULTS[main_type]
    await message.answer("📊 <b>Тест завершен! Твой персональный разбор:</b>")
    await message.answer(res['msg1'])
    await message.answer(res['msg2'])
    await message.answer(res['msg3'])
    await message.answer(res['msg4'])
    await state.clear()
    if user_id in user_data: del user_data[user_id]

async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
