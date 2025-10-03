import os
import json
import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command, CommandStart

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# Получаем токен и данные из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
DONATE_SBP = os.getenv("DONATE_SBP", "https://example.com")  # замени на свою СБП-ссылку

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

# Загружаем тест
with open("data/test1.json", "r", encoding="utf-8") as f:
    TEST_DATA = json.load(f)

# FSM для прохождения теста
class TestState(StatesGroup):
    answering = State()
    waiting_for_friend = State()

# База данных в памяти (для демо; в реальности — SQLite)
users = {}

# Проверка подписки
async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False

# Главное меню
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    referrer_id = None

    # Обработка реферальной ссылки
    if message.text and len(message.text.split()) > 1:
        ref = message.text.split()[1]
        if ref.startswith("ref"):
            try:
                referrer_id = int(ref[3:])
                users.setdefault(user_id, {})["referrer"] = referrer_id
            except:
                pass

    # Инициализация пользователя
    users.setdefault(user_id, {"score": 0, "current_question": 0, "done": False, "got_guide": False})

    # Проверка подписки
    if not await check_subscription(user_id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Подписаться на канал", url=f"https://t.me/{CHANNEL_ID[1:]}")],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")]
        ])
        await message.answer("Пожалуйста, подпишитесь на наш канал, чтобы пройти тест ❤️", reply_markup=kb)
        return

    # Если уже прошёл тест
    if users[user_id]["done"]:
        await show_result(message, user_id)
        return

    # Начало теста
    await message.answer(TEST_DATA["description"])
    await start_question(message, user_id, state)

# Проверка подписки по кнопке
@router.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if await check_subscription(user_id):
        await callback.message.edit_text("Спасибо за подписку! ❤️\nНачинаем тест...")
        await start_question(callback.message, user_id, state)
    else:
        await callback.answer("Вы не подписаны! Пожалуйста, подпишитесь.", show_alert=True)

# Отправка вопроса
async def start_question(message: Message, user_id: int, state: FSMContext):
    q_index = users[user_id]["current_question"]
    if q_index >= len(TEST_DATA["questions"]):
        # Тест завершён
        users[user_id]["done"] = True
        await show_result(message, user_id)
        return

    question = TEST_DATA["questions"][q_index]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"A) {question['options'][0]}", callback_data=f"ans_0")],
        [InlineKeyboardButton(text=f"B) {question['options'][1]}", callback_data=f"ans_1")],
        [InlineKeyboardButton(text=f"C) {question['options'][2]}", callback_data=f"ans_2")],
        [InlineKeyboardButton(text=f"D) {question['options'][3]}", callback_data=f"ans_3")],
    ])
    await message.answer(f"Вопрос {q_index + 1} из {len(TEST_DATA['questions'])}:\n\n{question['text']}", reply_markup=kb)
    await state.set_state(TestState.answering)

# Обработка ответа
@router.callback_query(TestState.answering, F.data.startswith("ans_"))
async def handle_answer(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    answer = int(callback.data.split("_")[1])
    users[user_id]["score"] += answer
    users[user_id]["current_question"] += 1

    await callback.answer()
    await start_question(callback.message, user_id, state)

# Показ результата
async def show_result(message: Message, user_id: int):
    score = users[user_id]["score"]
    result = None
    for r in TEST_DATA["results"]:
        if r["min"] <= score <= r["max"]:
            result = r
            break

    if not result:
        result = TEST_DATA["results"][-1]

    text = f"💔 Ваш результат: **{result['title']}**\n\n{result['text']}\n\n{TEST_DATA['guide_text']}"

    # Реферальная ссылка
    ref_link = f"https://t.me/{(await bot.me).username}?start=ref{user_id}"
    text += f"\n\n✨ Хотите получить **подробный гайд**? Отправьте эту ссылку другу:\n{ref_link}\n\nКак только друг пройдёт тест — гайд пришлют вам!"

    # Кнопка доната
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💝 Поддержать автора", url=DONATE_SBP)]
    ])

    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

# Обработка новых пользователей (рефералов)
@router.message(CommandStart())
async def handle_referral(message: Message):
    # Уже обработано в основном /start
    pass

# Основной запуск
async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
