import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, PreCheckoutQuery
from aiohttp import web

import config
from questions import QUESTIONS
from results import get_result_text

logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

class TestStates(StatesGroup):
    answering = State()
    waiting_payment = State()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (Health Check) ---
async def handle_health_check(request):
    return web.Response(text="Bot is alive!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server active on port {port}")

# --- ФУНКЦИИ БОТА ---
async def send_question(message_or_callback, state: FSMContext):
    data = await state.get_data()
    q_index = data.get("q_index", 0)

    if q_index >= len(QUESTIONS):
        # Подсчет результатов
        scores = data.get("scores", {})
        dominant_type = max(scores, key=scores.get) if scores else "frozen"
        await state.update_data(dominant_type=dominant_type)

        if config.SKIP_PAYMENT:
            report = get_result_text(dominant_type)
            if isinstance(message_or_callback, types.CallbackQuery):
                await message_or_callback.message.answer(report)
            else:
                await message_or_callback.answer(report)
            await state.clear()
        else:
            await state.set_state(TestStates.waiting_payment)
            prices = [LabeledPrice(label="Персональный разбор тормоза", amount=config.TEST_PRICE)]
            
            target_msg = message_or_callback.message if isinstance(message_or_callback, types.CallbackQuery) else message_or_callback
            await target_msg.answer_invoice(
                title="🧠 Твой разбор и 5-шаговый план",
                description="Полная расшифровка типа торможения и стратегия выхода из застоя.",
                provider_token=config.PROVIDER_TOKEN,
                currency="RUB",
                prices=prices,
                start_parameter="brake-diagnostic",
                payload=f"payload_brake_{target_msg.from_user.id}"
            )
        return

    q = QUESTIONS[q_index]
    
    # Формируем текст сообщения (Вопрос + Варианты A, B, C, D)
    text_lines = [f"<b>{q['text']}</b>\n"]
    keyboard_buttons = []
    
    for opt in q["options"]:
        text_lines.append(f"<b>Вариант {opt['label']}:</b> {opt['text']}")
        keyboard_buttons.append(
            InlineKeyboardButton(text=f"Вариант {opt['label']}", callback_data=f"ans_{opt['label']}")
        )

    # Группируем кнопки по 2 в ряд
    rows = [keyboard_buttons[i:i + 2] for i in range(0, len(keyboard_buttons), 2)]
    reply_markup = InlineKeyboardMarkup(inline_keyboard=rows)

    full_text = "\n\n".join(text_lines)

    if isinstance(message_or_callback, types.CallbackQuery):
        await message_or_callback.message.answer(full_text, reply_markup=reply_markup)
    else:
        await message_or_callback.answer(full_text, reply_markup=reply_markup)

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    sales_text = (
        "🧠 <b>ПОЧЕМУ ТЫ ТОПЧЕШЬСЯ НА МЕСТЕ И КАК ЭТО ИСПРАВИТЬ?</b>\n\n"
        "Ты прочитал десятки книг, прошел кучу курсов, но доход и жизнь не меняются? "
        "Дело вообще не в лени или отсутствии знаний.\n\n"
        "Существует <b>8 психологических типов торможения</b>: Перфекционист, Спасатель, Мечтатель, Контролёр, Самозванец, Выгоревший, Хаотик и Замороженный.\n\n"
        "🎯 <b>Пройди диагностику из 16 вопросов за 3 минуты и узнай:</b>\n"
        "• Твой главный психологический блок\n"
        "• Реальную причину, почему мозг тебя блокирует\n"
        "• Пошаговый план из 5 действий, как сорваться с места\n\n"
        "💳 <b>Стоимость полного разбора: 199 руб.</b> (вместо 5 000 руб. за сессию у психолога)\n\n"
        "Нажми кнопку ниже, чтобы начать тест!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Начать диагностику", callback_data="start_test")]
    ])
    await message.answer(sales_text, reply_markup=kb)

@dp.callback_query(F.data == "start_test")
async def start_test_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(TestStates.answering)
    await state.update_data(q_index=0, scores={})
    await send_question(callback, state)

@dp.callback_query(TestStates.answering, F.data.startswith("ans_"))
async def handle_answer(callback: types.CallbackQuery, state: FSMContext):
    ans_label = callback.data.split("_")[1]
    
    # Снимаем кнопки с отвеченного сообщения (чтобы не кликали повторно)
    await callback.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    q_index = data.get("q_index", 0)
    scores = data.get("scores", {})

    q = QUESTIONS[q_index]
    chosen_opt = next((o for o in q["options"] if o["label"] == ans_label), None)

    if chosen_opt:
        t_key = chosen_opt["type"]
        scores[t_key] = scores.get(t_key, 0) + 1

    await state.update_data(q_index=q_index + 1, scores=scores)
    await send_question(callback, state)

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message, state: FSMContext):
    data = await state.get_data()
    dominant_type = data.get("dominant_type", "frozen")
    report = get_result_text(dominant_type)
    
    await message.answer("✅ <b>Оплата успешно принята!</b> Формируем ваш разбор...")
    await message.answer(report)
    await state.clear()

async def main():
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
