import os
import json
import logging
import random
import aiohttp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command, CommandStart

logging.basicConfig(level=logging.INFO)

# === ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
DONATE_SBP = os.getenv("DONATE_SBP", "https://example.com")
GOOGLE_SCRIPT_URL = os.getenv("GOOGLE_SCRIPT_URL", "")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

# Загрузка теста
with open("data/test1.json", "r", encoding="utf-8") as f:
    TEST_DATA = json.load(f)

# FSM
class TestState(StatesGroup):
    answering = State()
    waiting_for_email = State()
    waiting_for_consent = State()

# Временное хранилище (в продакшене — SQLite + Google Sheets)
user_sessions = {}

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

async def send_to_sheet(action: str, user_id: int, **kwargs):
    if not GOOGLE_SCRIPT_URL:
        return
    try:
        async with aiohttp.ClientSession() as session:
            payload = {"action": action, "user_id": user_id, **kwargs}
            await session.post(GOOGLE_SCRIPT_URL, json=payload)
    except Exception as e:
        logging.error(f"Ошибка отправки в Google Sheets: {e}")

async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🧠 Психологические тесты")]],
        resize_keyboard=True,
        one_time_keyboard=False
    )

def get_tests_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💔 Тип привязанности", callback_data="test_attachment")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_menu")]
    ])
    return kb

def get_back_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_tests")]
    ])

# === ОСНОВНЫЕ ХЕНДЛЕРЫ ===

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    
    # Обработка реферала
    referrer_id = None
    if len(message.text.split()) > 1:
        ref = message.text.split()[1]
        if ref.startswith("ref"):
            try:
                referrer_id = int(ref[3:])
                # Уведомляем реферера, что друг прошёл
                if referrer_id in user_sessions:
                    user_sessions[referrer_id]["friends_completed"] = user_sessions[referrer_id].get("friends_completed", 0) + 1
                    fc = user_sessions[referrer_id]["friends_completed"]
                    if fc == 1:
                        await bot.send_message(referrer_id, "✅ Один друг уже прошёл тест! Ждём второго — и вы получите гайд.")
                    elif fc >= 2:
                        await bot.send_message(referrer_id, "🎉 Два друга прошли тест! Напишите свой email, и мы вышлем гайд.")
            except:
                pass

    # Инициализация сессии
    user_sessions[user_id] = {
        "score": 0,
        "current_question": 0,
        "done": False,
        "referrer": referrer_id,
        "friends_completed": 0
    }

    # Отправка в Google Sheets
    ref_link = f"https://t.me/psych_tests_bot?start=ref{user_id}"
    await send_to_sheet("new_user", user_id, username=username, ref_link=ref_link)

    if not await check_subscription(user_id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Подписаться", url=f"https://t.me/{CHANNEL_ID[1:]}")],
            [InlineKeyboardButton(text="✅ Проверить", callback_data="check_sub")]
        ])
        await message.answer("Подпишитесь на канал, чтобы пройти тест ❤️", reply_markup=kb)
        return

    await message.answer("Выберите раздел:", reply_markup=get_main_menu())

# === МЕНЮ ===

@router.message(F.text == "🧠 Психологические тесты")
async def show_tests(message: Message):
    await message.answer("Выберите тест:", reply_markup=get_tests_menu())

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.message.answer("Выберите раздел:", reply_markup=get_main_menu())

@router.callback_query(F.data == "back_to_tests")
async def back_to_tests(callback: CallbackQuery):
    await callback.message.answer("Выберите тест:", reply_markup=get_tests_menu())

# === ТЕСТ ===

@router.callback_query(F.data == "test_attachment")
async def start_test(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    fake_count = random.randint(1200, 1500)
    await callback.message.answer(
        f"Вы — 1 из {fake_count} прошедших тест в этом месяце! 🌟\n\n{TEST_DATA['description']}",
        reply_markup=get_back_button()
    )
    await ask_question(callback.message, user_id, state)

async def ask_question(message: Message, user_id: int, state: FSMContext):
    q_index = user_sessions[user_id]["current_question"]
    if q_index >= len(TEST_DATA["questions"]):
        user_sessions[user_id]["done"] = True
        await show_result(message, user_id)
        return

    question = TEST_DATA["questions"][q_index]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"А) {question['options'][0]}", callback_data="ans_0")],
        [InlineKeyboardButton(text=f"Б) {question['options'][1]}", callback_data="ans_1")],
        [InlineKeyboardButton(text=f"В) {question['options'][2]}", callback_data="ans_2")],
        [InlineKeyboardButton(text=f"Г) {question['options'][3]}", callback_data="ans_3")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_tests")]
    ])
    await message.answer(f"Вопрос {q_index + 1} из {len(TEST_DATA['questions'])}:\n\n{question['text']}", reply_markup=kb)
    await state.set_state(TestState.answering)

@router.callback_query(TestState.answering)
async def handle_answer(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = callback.data
    if data.startswith("ans_"):
        answer_value = int(data.split("_")[1])
        user_sessions[user_id]["score"] += answer_value
        user_sessions[user_id]["current_question"] += 1
        await callback.answer()
        await ask_question(callback.message, user_id, state)
    elif data == "back_to_tests":
        await callback.message.answer("Выберите тест:", reply_markup=get_tests_menu())

# === РЕЗУЛЬТАТ ===

async def show_result(message: Message, user_id: int):
    score = user_sessions[user_id]["score"]
    result = next((r for r in TEST_DATA["results"] if r["min"] <= score <= r["max"]), TEST_DATA["results"][-1])

    # Персонализированный призыв
    ref_link = f"https://t.me/psych_tests_bot?start=ref{user_id}"
    if score <= 25:
        call_to_action = f"✨ Хотите сделать ваши отношения ещё глубже? Отправьте эту ссылку **2 друзьям**:\n{ref_link}\n\nКогда оба пройдут тест — напишите email, и мы вышлем гайд бесплатно!"
    elif score <= 50:
        call_to_action = f"✨ Хотите выйти из тревожной привязанности? Отправьте эту ссылку **2 друзьям**:\n{ref_link}\n\nКогда оба пройдут тест — напишите email, и мы вышлем гайд бесплатно!"
    elif score <= 75:
        call_to_action = f"✨ Вам срочно нужен инструмент, чтобы выйти из эмоциональной ловушки. Отправьте эту ссылку **2 друзьям**:\n{ref_link}\n\nКогда оба пройдут тест — напишите email, и мы вышлем гайд бесплатно!"
    else:
        call_to_action = f"✨ Это кризис, и вам нужна поддержка. Отправьте эту ссылку **2 друзьям**:\n{ref_link}\n\nКогда оба пройдут тест — напишите email, и мы вышлем гайд бесплатно!"

    text = f"💔 Ваш результат: **{result['title']}**\n\n{result['text']}\n\n{call_to_action}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📧 Отправить email", callback_data="request_email")],
        [InlineKeyboardButton(text="💝 Под
