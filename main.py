import os
import json
import logging
import random
import aiohttp
import re
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

# Временное хранилище
user_sessions = {}

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def escape_markdown_v2(text: str) -> str:
    """Экранирует спецсимволы для MarkdownV2"""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', text)

def get_email_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📧 Да, я хочу получить гайд", callback_data="request_email")]
    ])

def get_test_menu_after_email():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧠 Выбрать другой тест", callback_data="back_to_tests")]
    ])

def get_tests_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💔 Тип привязанности", callback_data="test_attachment")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_menu")]
    ])

def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🧠 Психологические тесты")]],
        resize_keyboard=True,
        one_time_keyboard=False
    )

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

# === ХЕНДЛЕРЫ ===

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    referrer_id = None
    if len(message.text.split()) > 1:
        ref = message.text.split()[1]
        if ref.startswith("ref"):
            try:
                referrer_id = int(ref[3:])
                if referrer_id in user_sessions:
                    user_sessions[referrer_id]["friends_completed"] = user_sessions[referrer_id].get("friends_completed", 0) + 1
                    fc = user_sessions[referrer_id]["friends_completed"]
                    if fc == 1:
                        await bot.send_message(referrer_id, "✅ Один друг уже прошёл тест! Ждём второго — и вы получите гайд.")
                    elif fc >= 2:
                        await bot.send_message(
                            referrer_id,
                            "🎉 Два друга прошли тест! Напишите свой email, и мы вышлем гайд.",
                            reply_markup=get_email_button()
                        )
            except Exception as e:
                logging.error(f"Ошибка при обработке реферала: {e}")
                pass
    user_sessions[user_id] = {
        "score": 0,
        "current_question": 0,
        "done": False,
        "referrer": referrer_id,
        "friends_completed": 0
    }
    ref_link = f"https://t.me/my_psych_tester_bot?start=ref{user_id}"
    await send_to_sheet("new_user", user_id, username=username, ref_link=ref_link)
    if not await check_subscription(user_id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Подписаться на канал", url=f"https://t.me/{CHANNEL_ID[1:]}")],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")]
        ])
        await message.answer("Пожалуйста, подпишитесь на наш канал, чтобы пройти тест ❤️", reply_markup=kb)
        return
    await message.answer("Выберите раздел:", reply_markup=get_main_menu())

@router.message(F.text == "🧠 Психологические тесты")
async def show_tests(message: Message):
    await message.answer("Выберите тест:", reply_markup=get_tests_menu())

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.message.answer("Выберите раздел:", reply_markup=get_main_menu())

@router.callback_query(F.data == "back_to_tests")
async def back_to_tests(callback: CallbackQuery):
    await callback.message.answer("Выберите тест:", reply_markup=get_tests_menu())

@router.callback_query(F.data == "test_attachment")
async def start_test(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    fake_count = random.randint(1200, 1500)
    await callback.message.answer(
        f"Вы — 1 из {fake_count} прошедших тест в этом месяце! 🌟\n{TEST_DATA['description']}"
    )
    await ask_question(callback.message, user_id, state)

async def ask_question(message: Message, user_id: int, state: FSMContext):
    q_index = user_sessions[user_id]["current_question"]
    if q_index >= len(TEST_DATA["questions"]):
        user_sessions[user_id]["done"] = True
        await state.clear()
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
    await message.answer(f"Вопрос {q_index + 1} из {len(TEST_DATA['questions'])}:\n{question['text']}", reply_markup=kb)
    if q_index == 0:
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
        await state.clear()
        await callback.message.answer("Выберите тест:", reply_markup=get_tests_menu())

async def show_result(message: Message, user_id: int):
    score = user_sessions[user_id]["score"]
    result = next((r for r in TEST_DATA["results"] if r["min"] <= score <= r["max"]), TEST_DATA["results"][-1])
    ref_link = f"https://t.me/my_psych_tester_bot?start=ref{user_id}"
    call_to_action = f"✨ Отправьте эту ссылку **2 друзьям**:\n{ref_link}\nКогда оба пройдут тест — нажмите кнопку ниже, и мы вышлем гайд."
    escaped_title = escape_markdown_v2(result['title'])
    escaped_text = escape_markdown_v2(result['text'])
    escaped_call_to_action = escape_markdown_v2(call_to_action)
    text = f"💔 Ваш результат: *{escaped_title}*\n{escaped_text}\n{escaped_call_to_action}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📧 Получить гайд", callback_data="request_email")],
        [InlineKeyboardButton(text="💝 Поддержать автора", url=DONATE_SBP)],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_tests")]
    ])
    try:
        await message.answer(text, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e:
        logging.error(f"Ошибка отправки результата пользователю {user_id}: {e}")

@router.callback_query(F.data == "request_email")
async def request_email(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    friends = user_sessions[user_id].get("friends_completed", 0)
    if friends < 2:
        await callback.message.answer(f"Пока что прошёл(и) {friends} друг(а). Нужно 2, чтобы получить гайд.")
        return
    await callback.message.answer(
        "📧 Введите ваш email:\n"
        "✅ Нажимая «Отправить», вы даёте согласие на обработку персональных данных в соответствии с ФЗ-152.\n"
        "❗️ Гайд будет отправлен на этот email в течение 24 часов. Проверьте папку «Спам», если не получили письмо."
    )
    await state.set_state(TestState.waiting_for_email)

@router.message(TestState.waiting_for_email)
async def handle_email(message: Message, state: FSMContext):
    email = message.text.strip()
    if "@" not in email or "." not in email:
        await message.answer("Некорректный email. Попробуйте снова:")
        return
    user_id = message.from_user.id
    score = user_sessions.get(user_id, {}).get("score", 0)
    await send_to_sheet("email_submitted", user_id, email=email, score=score)
    await message.answer(
        "Спасибо
