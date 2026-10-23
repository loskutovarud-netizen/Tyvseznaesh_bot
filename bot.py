# ============================================
# ОСНОВНОЙ ФАЙЛ БОТА
# ============================================
# Запуск: python bot.py

import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery, Message
)

from config import (
    BOT_TOKEN, PROVIDER_TOKEN, TEST_PRICE,
    SKIP_PAYMENT, CURRENCY, ADMIN_ID
)
from questions import QUESTIONS
from results import RESULTS, TYPE_NAMES, TYPE_EMOJI

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()


# ============================================
# СОСТОЯНИЯ
# ============================================
class TestStates(StatesGroup):
    waiting_payment = State()
    in_progress = State()
    completed = State()


# ============================================
# ХРАНИЛИЩЕ ДАННЫХ (MVP)
# Для продакшена замени на PostgreSQL / Redis
# ============================================
users_db: dict = {}


def get_user(user_id: int) -> dict:
    if user_id not in users_db:
        users_db[user_id] = {
            "paid": False,
            "scores": {
                "collector": 0,
                "analyst": 0,
                "frozen": 0,
                "perfectionist": 0,
                "loner": 0,
            },
            "current_q": 0,
            "completed": False,
        }
    return users_db[user_id]


# ============================================
# /start
# ============================================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)

    if user["completed"]:
        await message.answer(
            "✅ Ты уже прошёл тест «Где мой тормоз?»\n\n"
            "Результат был в предыдущих сообщениях — "
            "пролистай выше.\n\n"
            "Если хочешь пройти заново — напиши /reset"
        )
        return

    if user["paid"] or SKIP_PAYMENT:
        await start_test(message, state)
        return

    await state.set_state(TestStates.waiting_payment)
    await message.answer(
        "🧠 <b>Тест «Где мой тормоз?»</b>\n\n"
        "Ты знаешь, что делать. Читал, смотрел, изучал.\n"
        "Но ничего не меняется.\n\n"
        "Этот тест покажет, <b>что именно</b> тебя "
        "останавливает — и как это починить.\n\n"
        "📊 18 вопросов · ⏱ 4 минуты · 5 типов\n\n"
        "Стоимость: <b>299 ₽</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="💳 Оплатить и пройти тест",
                callback_data="pay"
            )],
        ])
    )


# ============================================
# ОПЛАТА
# ============================================
@dp.callback_query(F.data == "pay")
async def process_pay(callback: types.CallbackQuery, state: FSMContext):
    if SKIP_PAYMENT:
        await callback.answer()
        await start_test(callback.message, state)
        return

    await callback.answer()
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Тест «Где мой тормоз?»",
        description="18 вопросов, 5 типов, персональный план действий",
        payload="test_access",
        provider_token=PROVIDER_TOKEN,
        currency=CURRENCY,
        prices=[LabeledPrice(
            label="Доступ к тесту",
            amount=TEST_PRICE
        )],
    )


@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(
        pre_checkout_query.id, ok=True
    )


@dp.message(F.successful_payment)
async def successful_payment(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    user["paid"] = True

    await message.answer(
        "✅ Оплата получена! Спасибо.\n"
        "Запускаю тест..."
    )
    await start_test(message, state)

    # Уведомление админу
    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"💰 Новая оплата!\n"
                f"Пользователь: @{message.from_user.username or message.from_user.id}\n"
                f"Сумма: {TEST_PRICE // 100} ₽"
            )
        except Exception:
            pass


# ============================================
# ЗАПУСК ТЕСТА
# ============================================
async def start_test(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    user["current_q"] = 0
    user["scores"] = {
        "collector": 0, "analyst": 0,
        "frozen": 0, "perfectionist": 0, "loner": 0,
    }
    await state.set_state(TestStates.in_progress)
    await send_question(message, 0)


async def send_question(message: Message, q_index: int):
    q = QUESTIONS[q_index]
    total = len(QUESTIONS)
    progress = "█" * (q_index + 1) + "░" * (total - q_index - 1)

    text = (
        f"<b>{q['category']}</b> ({q_index + 1}/{total})\n"
        f"<code>{progress}</code>\n\n"
        f"{q['text']}"
    )

    buttons = []
    for i, (emoji, answer_text, _) in enumerate(q["answers"]):
        buttons.append([InlineKeyboardButton(
            text=f"{emoji} {answer_text}",
            callback_data=f"q{q_index}_{i}"
        )])

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# ============================================
# ОБРАБОТКА ОТВЕТОВ
# ============================================
@dp.callback_query(F.data.startswith("q"))
async def process_answer(
    callback: types.CallbackQuery,
    state: FSMContext
):
    user = get_user(callback.from_user.id)

    if user["completed"]:
        await callback.answer("Тест уже пройден", show_alert=True)
        return

    # Парсим callback_data: "q5_2" → вопрос 5, ответ 2
    data = callback.data.replace("q", "").split("_")
    q_index = int(data[0])
    a_index = int(data[1])

    # Проверяем, что это актуальный вопрос
    if q_index != user["current_q"]:
        await callback.answer()
        return

    await callback.answer()

    # Начисляем баллы
    q = QUESTIONS[q_index]
    answer_scores = q["answers"][a_index][2]
    for key, val in answer_scores.items():
        user["scores"][key] += val

    # Следующий вопрос или результат
    next_q = q_index + 1
    if next_q < len(QUESTIONS):
        user["current_q"] = next_q
        await send_question(callback.message, next_q)
    else:
        user["completed"] = True
        await state.set_state(TestStates.completed)
        await show_loading(callback.message)
        await asyncio.sleep(3)
        await send_result(callback.message, user["scores"])


# ============================================
# ЗАГРУЗКА (имитация анализа)
# ============================================
async def show_loading(message: Message):
    await message.answer(
        "⏳ <b>Анализируем ответы...</b>\n\n"
        "⏳ Паттерны поведения...\n"
        "⏳ Эмоциональные блоки...\n"
        "⏳ Формируем рекомендации..."
    )


# ============================================
# РЕЗУЛЬТАТ
# ============================================
async def send_result(message: Message, scores: dict):
    # Определяем доминантный тип
    total = sum(scores.values()) or 1
    sorted_types = sorted(
        scores.items(), key=lambda x: x[1], reverse=True
    )
    main_type = sorted_types[0][0]
    data = RESULTS[main_type]

    # Сообщение 0: Профиль
    profile_lines = ["📊 <b>Твой профиль застревания:</b>\n"]
    bars = {"collector": "🟡", "analyst": "🔵", "frozen": "🟣",
            "perfectionist": "🔴", "loner": "🟢"}
    for t, s in sorted_types:
        pct = round(s / total * 100)
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        profile_lines.append(
            f"{bars[t]} {TYPE_NAMES[t]}: {bar} {pct}%"
        )
    await message.answer("\n".join(profile_lines))

    await asyncio.sleep(0.5)

    # Сообщения 1–4: результат
    for key in ["msg1", "msg2", "msg3", "msg4"]:
        await message.answer(data[key])
        await asyncio.sleep(0.8)


# ============================================
# СБРОС (для повторного прохождения)
# ============================================
@dp.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in users_db:
        del users_db[user_id]
    await state.clear()
    await message.answer(
        "🔄 Данные сброшены. Напиши /start, чтобы начать заново."
    )


# ============================================
# СТАТИСТИКА (для админа)
# ============================================
@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    total_users = len(users_db)
    paid_users = sum(1 for u in users_db.values() if u["paid"])
    completed = sum(1 for u in users_db.values() if u["completed"])

    type_counts = {}
    for u in users_db.values():
        if u["completed"]:
            main = max(u["scores"], key=u["scores"].get)
            type_counts[main] = type_counts.get(main, 0) + 1

    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"💳 Оплатили: {paid_users}\n"
        f"✅ Прошли тест: {completed}\n\n"
        f"<b>Распределение типов:</b>\n"
    )
    for t, c in sorted(
        type_counts.items(), key=lambda x: x[1], reverse=True
    ):
        text += f"{TYPE_EMOJI[t]} {TYPE_NAMES[t]}: {c}\n"

    await message.answer(text)


# ============================================
# ЗАПУСК
# ============================================
async def main():
    logger.info("🤖 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
