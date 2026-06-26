import asyncio
import tomllib
import aiohttp
import hashlib
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime

with open("config.toml", "rb") as f:
    config = tomllib.load(f)

FASTAPI_URL = config.get("server", {}).get("rf_api_url", "http://127.0.0.1:8000")
POLICY_PATH = "storage/policy_signed.pdf"
bot = Bot(token=config["telegram"]["token"])
dp = Dispatcher(storage=MemoryStorage())

class RegisterState(StatesGroup):
    waiting_for_fio = State()
    waiting_for_birth_date = State()

def get_file_sha256(file_path: str) -> str:
    if not os.path.exists(file_path):
        return ""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

async def sync_policy_with_db():
    file_hash = get_file_sha256(POLICY_PATH)
    if not file_hash:
        print("⚠️ Файл политики не найден, синхронизация невозможна.")
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{FASTAPI_URL}/api/v1/policy/sync", json={"file_hash": file_hash}) as resp:
                if resp.status == 200:
                    print("✅ Политика синхронизирована с БД.")
                else:
                    print(f"❌ Ошибка синхронизации политики: {resp.status}")
    except Exception as e:
        print(f"❌ Не удалось подключиться к серверу для синхронизации: {e}")

async def notify_admins(tg_id: int, full_name: str, birth_date: str):
    for admin_id in config["admins"]["ids"]:
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Одобрить", callback_data=f"approve_{tg_id}")
        msg = f"🔔 Новая заявка на доступ:\nФИО: {full_name}\nДата рождения: {birth_date}\nID: {tg_id}"
        try:
            await bot.send_message(admin_id, msg, reply_markup=builder.as_markup())
        except:
            pass

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    tg_id = message.from_user.id
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{FASTAPI_URL}/api/v1/employee/check", json={"telegram_id": tg_id}, timeout=5) as resp:
                data = await resp.json()
    except Exception:
        await message.answer("❌ Ошибка связи с сервером БД. Попробуйте позже.")
        return

    if "policy_id" in data and data["policy_id"]:
        await state.update_data(policy_id=data["policy_id"])

    if not data["allowed"]:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Принимаю политику и хочу зарегистрироваться", callback_data="accept_policy")
        ]])
        await message.answer_document(
            FSInputFile(POLICY_PATH),
            caption="Здравствуйте! Вы не найдены в корпоративной базе. Для регистрации необходимо принять Политику обработки ПДн [ФЗ-152].",
            reply_markup=keyboard
        )
        return

    if not data["is_consented"]:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Подписать ПЭП", callback_data=f"sign_{data['policy_id']}")
        ]])
        await message.answer_document(
            FSInputFile(POLICY_PATH),
            caption="Для доступа подпишите согласие (ПЭП):",
            reply_markup=keyboard
        )
    else:
        await message.answer(f"Рады видеть вас, {data['full_name']}. Доступ активен.")

async def check_birthdays():
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{FASTAPI_URL}/api/v1/employee/birthday_today") as resp:
            if resp.status == 200:
                people = await resp.json()
                for person in people:
                    await bot.send_message(
                        chat_id=-1003855264349,
                        text=f"🎉 Сегодня день рождения у {person['full_name']}! Поздравляем!"
                    )

@dp.callback_query(F.data == "accept_policy")
async def accept_policy(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer("Политика принята. Введите ваше ФИО:")
    await state.set_state(RegisterState.waiting_for_fio)

@dp.message(RegisterState.waiting_for_fio)
async def process_fio(message: types.Message, state: FSMContext):
    await state.update_data(fio=message.text)
    await message.answer("Принято. Теперь введите дату рождения (ГГГГ-ММ-ДД):")
    await state.set_state(RegisterState.waiting_for_birth_date)

@dp.message(RegisterState.waiting_for_birth_date)
async def process_birth_date(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    fio = user_data['fio']
    birth_date = message.text
    tg_id = message.from_user.id
    policy_id = user_data.get('policy_id', 1)

    payload = {
        "telegram_id": int(tg_id),
        "full_name": str(fio),
        "birth_date": str(birth_date),
        "is_consented": True,
        "policy_id": int(policy_id)
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{FASTAPI_URL}/api/v1/employee/register", json=payload) as resp:
            if resp.status == 200:
                await message.answer("✅ Регистрация завершена. Ожидайте одобрения администратором.")
                await notify_admins(tg_id, fio, birth_date)
            else:
                await message.answer(f"❌ Ошибка при регистрации (код {resp.status}).")

    await state.clear()

@dp.callback_query(F.data.startswith("sign_"))
async def handle_signature(callback: types.CallbackQuery):
    tg_id = callback.from_user.id
    async with aiohttp.ClientSession() as session:
        await session.post(
            f"{FASTAPI_URL}/api/v1/employee/consent",
            json={"telegram_id": tg_id, "policy_id": int(callback.data.split("_")[1])}
        )
    await callback.message.edit_caption(caption="✅ ПЭП зафиксирована. Ожидайте одобрения.")

@dp.callback_query(F.data.startswith("approve_"))
async def admin_approve(callback: types.CallbackQuery):
    if callback.from_user.id not in config["admins"]["ids"]:
        return
    target_id = int(callback.data.split("_")[1])
    async with aiohttp.ClientSession() as session:
        await session.post(
            f"{FASTAPI_URL}/api/v1/employee/verify",
            json={"telegram_id": target_id, "admin_name": callback.from_user.full_name}
        )
    await callback.message.edit_text(f"✅ Сотрудник {target_id} подтвержден.")
    await bot.send_message(target_id, "🎉 Ваш профиль подтвержден!")

async def main():
    print("Синхронизация политики...")
    await sync_policy_with_db()
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(check_birthdays, 'cron', hour=11, minute=47)
    scheduler.start()

    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
