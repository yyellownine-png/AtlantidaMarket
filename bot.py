import asyncio
import logging
import os
from datetime import datetime

import aiosqlite
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN or BOT_TOKEN == "ТОКЕН_ТВОЕГО_БОТА":
    raise RuntimeError("В .env не указан настоящий BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

DB = "atlantida.db"


# =========================
# STATES
# =========================

class SellStates(StatesGroup):
    category = State()
    name = State()
    amount = State()
    price = State()
    description = State()


class SearchStates(StatesGroup):
    query = State()


# =========================
# CATEGORIES
# =========================

CATEGORIES = {
    "stars": "⭐ Telegram Stars",
    "gifts": "🎁 Telegram Gifts",
    "nft": "💎 NFT",
    "ton": "💠 TON",
    "other": "📦 Другое",
}


# =========================
# DATABASE
# =========================

async def init_db():
    async with aiosqlite.connect(DB) as db:

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER,
                category TEXT,
                name TEXT,
                amount TEXT,
                price TEXT,
                description TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER,
                buyer_id INTEGER,
                seller_id INTEGER,
                status TEXT DEFAULT 'created',
                created_at TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS seller_payment_methods (
                seller_id INTEGER PRIMARY KEY,
                crypto_send TEXT,
                ton_wallet TEXT,
                card_info TEXT,
                updated_at TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER,
                reporter_id INTEGER,
                reason TEXT,
                created_at TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER,
                buyer_id INTEGER,
                rating INTEGER,
                text TEXT,
                created_at TEXT
            )
        """)

        await db.commit()


async def save_user(user):
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            INSERT INTO users (id, username, first_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            datetime.now().isoformat()
        ))
        await db.commit()


# =========================
# KEYBOARDS
# =========================

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🛒 Купить"),
                KeyboardButton(text="📤 Продать")
            ],
            [
                KeyboardButton(text="🔎 Поиск"),
                KeyboardButton(text="📋 Мои объявления")
            ],
            [
                KeyboardButton(text="🤝 Мои сделки"),
                KeyboardButton(text="👤 Профиль")
            ],
            [
                KeyboardButton(text="🛡 Помощь")
            ]
        ],
        resize_keyboard=True
    )


def categories_keyboard(prefix="filter"):
    rows = []

    for key, name in CATEGORIES.items():
        rows.append([
            InlineKeyboardButton(
                text=name,
                callback_data=f"{prefix}_{key}"
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="menu"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start(message: Message):
    await save_user(message.from_user)

    text = (
        "🌊 <b>ATLANTIDA MARKET</b>\n\n"
        "Добро пожаловать на P2P-маркетплейс.\n\n"
        "Здесь пользователи могут:\n"
        "🛒 покупать товары\n"
        "📤 создавать свои объявления\n"
        "🔎 искать нужные лоты\n"
        "🤝 создавать сделки\n"
        "⭐ получать отзывы\n\n"
        "⚠️ <b>РЕЖИМ ТЕСТОВЫЙ</b>\n"
        "Бот не принимает и не хранит реальные деньги или криптовалюту.\n"
        "Сделки сейчас демонстрационные."
    )

    await message.answer(
        text,
        reply_markup=main_keyboard()
    )


@dp.message(Command("menu"))
async def menu(message: Message):
    await message.answer(
        "🌊 <b>ATLANTIDA MARKET</b>\n\nВыбери действие:",
        reply_markup=main_keyboard()
    )


# =========================
# BUY
# =========================

@dp.message(F.text == "🛒 Купить")
async def buy(message: Message):
    await message.answer(
        "🛒 <b>КАТАЛОГ</b>\n\nВыбери категорию:",
        reply_markup=categories_keyboard("filter")
    )


@dp.callback_query(F.data.startswith("filter_"))
async def filter_category(callback: CallbackQuery):
    category = callback.data.replace("filter_", "")

    if category not in CATEGORIES:
        await callback.answer("Ошибка")
        return

    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("""
            SELECT id, seller_id, name, amount, price
            FROM listings
            WHERE category=? AND status='active'
            ORDER BY id DESC
            LIMIT 20
        """, (category,))

        listings = await cursor.fetchall()

    if not listings:
        await callback.message.edit_text(
            f"{CATEGORIES[category]}\n\n"
            "Пока здесь нет активных объявлений.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="⬅️ Категории",
                    callback_data="buy_back"
                )]
            ])
        )
        await callback.answer()
        return

    text = f"{CATEGORIES[category]}\n\n"

    buttons = []

    for listing_id, seller_id, name, amount, price in listings:
        text += (
            f"#{listing_id} • <b>{name}</b>\n"
            f"Количество: {amount}\n"
            f"Цена: {price}\n\n"
        )

        buttons.append([
            InlineKeyboardButton(
                text=f"🔎 #{listing_id} {name}",
                callback_data=f"listing_{listing_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Категории",
            callback_data="buy_back"
        )
    ])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

    await callback.answer()


@dp.callback_query(F.data == "buy_back")
async def buy_back(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛒 <b>КАТАЛОГ</b>\n\nВыбери категорию:",
        reply_markup=categories_keyboard("filter")
    )
    await callback.answer()


# =========================
# LISTING DETAILS
# =========================

@dp.callback_query(F.data.startswith("listing_"))
async def listing_details(callback: CallbackQuery):
    try:
        listing_id = int(callback.data.split("_")[1])
    except:
        await callback.answer("Ошибка")
        return

    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("""
            SELECT
                l.id,
                l.seller_id,
                l.category,
                l.name,
                l.amount,
                l.price,
                l.description,
                l.created_at,
                u.username
            FROM listings l
            LEFT JOIN users u ON u.id=l.seller_id
            WHERE l.id=?
        """, (listing_id,))

        row = await cursor.fetchone()

    if not row:
        await callback.answer("Объявление не найдено", show_alert=True)
        return

    (
        lid,
        seller_id,
        category,
        name,
        amount,
        price,
        description,
        created_at,
        username
    ) = row

    username_text = f"@{username}" if username else "скрыт"

    text = (
        f"💎 <b>ОБЪЯВЛЕНИЕ #{lid}</b>\n\n"
        f"Категория: {CATEGORIES.get(category, category)}\n"
        f"Название: <b>{name}</b>\n"
        f"Количество: {amount}\n"
        f"Цена: <b>{price}</b>\n\n"
        f"Описание:\n{description or 'Без описания'}\n\n"
        f"👤 Продавец: {username_text}"
    )

    buttons = [
        [
            InlineKeyboardButton(
                text="🤝 Создать тестовую сделку",
                callback_data=f"deal_{lid}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🚨 Пожаловаться",
                callback_data=f"report_{lid}"
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"back_category_{category}"
            )
        ]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("back_category_"))
async def back_category(callback: CallbackQuery):
    category = callback.data.replace("back_category_", "")

    if category not in CATEGORIES:
        await callback.answer()
        return

    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("""
            SELECT id, name, amount, price
            FROM listings
            WHERE category=? AND status='active'
            ORDER BY id DESC
            LIMIT 20
        """, (category,))

        listings = await cursor.fetchall()

    text = f"{CATEGORIES[category]}\n\n"
    buttons = []

    for lid, name, amount, price in listings:
        text += f"#{lid} • {name} • {amount} • {price}\n"

        buttons.append([
            InlineKeyboardButton(
                text=f"🔎 #{lid} {name}",
                callback_data=f"listing_{lid}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Категории",
            callback_data="buy_back"
        )
    ])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

    await callback.answer()


# =========================
# CREATE DEAL
# =========================

@dp.callback_query(F.data.startswith("deal_"))
async def create_deal(callback: CallbackQuery):
    try:
        listing_id = int(callback.data.split("_")[1])
    except:
        await callback.answer("Ошибка")
        return

    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("""
            SELECT seller_id, status
            FROM listings
            WHERE id=?
        """, (listing_id,))

        row = await cursor.fetchone()

        if not row:
            await callback.answer(
                "Объявление не найдено",
                show_alert=True
            )
            return

        seller_id, status = row

        if seller_id == callback.from_user.id:
            await callback.answer(
                "Нельзя создать сделку со своим объявлением.",
                show_alert=True
            )
            return

        if status != "active":
            await callback.answer(
                "Объявление уже закрыто.",
                show_alert=True
            )
            return

        await db.execute("""
            INSERT INTO trades
            (listing_id, buyer_id, seller_id, status, created_at)
            VALUES (?, ?, ?, 'created', ?)
        """, (
            listing_id,
            callback.from_user.id,
            seller_id,
            datetime.now().isoformat()
        ))

        await db.commit()

    await callback.message.answer(
        "🤝 <b>ТЕСТОВАЯ СДЕЛКА СОЗДАНА</b>\n\n"
        f"Объявление: #{listing_id}\n\n"
        "⚠️ Это демонстрационный режим.\n"
        "Реальные деньги и криптовалюта через этого бота сейчас не передаются."
    )

    try:
        await bot.send_message(
            seller_id,
            "🔔 <b>Новое уведомление</b>\n\n"
            f"Пользователь создал тестовую сделку по объявлению #{listing_id}."
        )
    except:
        pass

    await callback.answer("Сделка создана")


# =========================
# SELL
# =========================

@dp.message(F.text == "📤 Продать")
async def sell(message: Message, state: FSMContext):
    await state.set_state(SellStates.category)

    buttons = []

    for key, name in CATEGORIES.items():
        buttons.append([
            InlineKeyboardButton(
                text=name,
                callback_data=f"sellcat_{key}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="❌ Отмена",
            callback_data="cancel_sell"
        )
    ])

    await message.answer(
        "📤 <b>НОВОЕ ОБЪЯВЛЕНИЕ</b>\n\n"
        "Выбери категорию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.callback_query(F.data.startswith("sellcat_"), SellStates.category)
async def sell_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.replace("sellcat_", "")

    if category not in CATEGORIES:
        await callback.answer("Ошибка")
        return

    await state.update_data(category=category)
    await state.set_state(SellStates.name)

    await callback.message.answer(
        "✏️ Введи название товара.\n\n"
        "Например: Telegram Stars 100"
    )

    await callback.answer()


@dp.message(SellStates.name)
async def sell_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(SellStates.amount)

    await message.answer(
        "🔢 Введи количество.\n\n"
        "Например: 100"
    )


@dp.message(SellStates.amount)
async def sell_amount(message: Message, state: FSMContext):
    await state.update_data(amount=message.text)
    await state.set_state(SellStates.price)

    await message.answer(
        "💰 Введи цену.\n\n"
        "Например: 150 RUB\n\n"
        "⚠️ В тестовом режиме это просто текстовая цена."
    )


@dp.message(SellStates.price)
async def sell_price(message: Message, state: FSMContext):
    await state.update_data(price=message.text)
    await state.set_state(SellStates.description)

    await message.answer(
        "📝 Напиши описание товара.\n\n"
        "Если описания нет — напиши «нет»."
    )


@dp.message(SellStates.description)
async def sell_description(message: Message, state: FSMContext):
    data = await state.get_data()

    description = message.text

    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("""
            INSERT INTO listings
            (seller_id, category, name, amount, price, description, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
        """, (
            message.from_user.id,
            data["category"],
            data["name"],
            data["amount"],
            data["price"],
            description,
            datetime.now().isoformat()
        ))

        listing_id = cursor.lastrowid

        await db.commit()

    await state.clear()

    await message.answer(
        "✅ <b>ОБЪЯВЛЕНИЕ СОЗДАНО</b>\n\n"
        f"Номер: #{listing_id}\n"
        f"Товар: {data['name']}\n"
        f"Количество: {data['amount']}\n"
        f"Цена: {data['price']}\n\n"
        "Теперь его могут увидеть покупатели.",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "cancel_sell")
async def cancel_sell(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    await callback.message.answer(
        "❌ Создание объявления отменено.",
        reply_markup=main_keyboard()
    )

    await callback.answer()


# =========================
# MY LISTINGS
# =========================

@dp.message(F.text == "📋 Мои объявления")
async def my_listings(message: Message):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("""
            SELECT id, name, amount, price, status
            FROM listings
            WHERE seller_id=?
            ORDER BY id DESC
        """, (message.from_user.id,))

        rows = await cursor.fetchall()

    if not rows:
        await message.answer(
            "📋 У тебя пока нет объявлений."
        )
        return

    text = "📋 <b>МОИ ОБЪЯВЛЕНИЯ</b>\n\n"
    buttons = []

    for lid, name, amount, price, status in rows:
        status_text = "🟢 активно" if status == "active" else "🔴 закрыто"

        text += (
            f"#{lid} • <b>{name}</b>\n"
            f"{amount} • {price}\n"
            f"{status_text}\n\n"
        )

        if status == "active":
            buttons.append([
                InlineKeyboardButton(
                    text=f"🔴 Закрыть #{lid}",
                    callback_data=f"close_{lid}"
                )
            ])

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        if buttons else None
    )


@dp.callback_query(F.data.startswith("close_"))
async def close_listing(callback: CallbackQuery):
    try:
        listing_id = int(callback.data.split("_")[1])
    except:
        await callback.answer("Ошибка")
        return

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            UPDATE listings
            SET status='closed'
            WHERE id=? AND seller_id=?
        """, (
            listing_id,
            callback.from_user.id
        ))

        await db.commit()

    await callback.message.answer(
        f"🔴 Объявление #{listing_id} закрыто."
    )

    await callback.answer("Закрыто")


# =========================
# MY TRADES
# =========================

@dp.message(F.text == "🤝 Мои сделки")
async def my_trades(message: Message):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("""
            SELECT id, listing_id, buyer_id, seller_id, status
            FROM trades
            WHERE buyer_id=? OR seller_id=?
            ORDER BY id DESC
        """, (
            message.from_user.id,
            message.from_user.id
        ))

        rows = await cursor.fetchall()

    if not rows:
        await message.answer(
            "🤝 У тебя пока нет сделок."
        )
        return

    text = "🤝 <b>МОИ СДЕЛКИ</b>\n\n"

    for tid, lid, buyer, seller, status in rows:
        role = "Покупатель" if buyer == message.from_user.id else "Продавец"

        text += (
            f"Сделка #{tid}\n"
            f"Объявление: #{lid}\n"
            f"Роль: {role}\n"
            f"Статус: {status}\n\n"
        )

    await message.answer(text)


# =========================
# PROFILE
# =========================

@dp.message(F.text == "👤 Профиль")
async def profile(message: Message):
    async with aiosqlite.connect(DB) as db:

        cursor = await db.execute("""
            SELECT COUNT(*)
            FROM listings
            WHERE seller_id=?
        """, (message.from_user.id,))

        listings_count = (await cursor.fetchone())[0]

        cursor = await db.execute("""
            SELECT COUNT(*)
            FROM trades
            WHERE buyer_id=? OR seller_id=?
        """, (
            message.from_user.id,
            message.from_user.id
        ))

        trades_count = (await cursor.fetchone())[0]

        cursor = await db.execute("""
            SELECT AVG(rating), COUNT(*)
            FROM reviews
            WHERE seller_id=?
        """, (message.from_user.id,))

        rating, reviews_count = await cursor.fetchone()

    rating_text = f"{rating:.1f}/5" if rating else "нет оценок"

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "не указан"
    )

    text = (
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        f"ID: <code>{message.from_user.id}</code>\n"
        f"Username: {username}\n\n"
        f"📋 Объявлений: {listings_count}\n"
        f"🤝 Сделок: {trades_count}\n"
        f"⭐ Рейтинг: {rating_text}\n"
        f"💬 Отзывов: {reviews_count}\n"
    )

    await message.answer(text)


# =========================
# SEARCH
# =========================

@dp.message(F.text == "🔎 Поиск")
async def search_start(message: Message, state: FSMContext):
    await state.set_state(SearchStates.query)

    await message.answer(
        "🔎 <b>ПОИСК</b>\n\n"
        "Напиши название товара.\n\n"
        "Например:\n"
        "Stars\n"
        "NFT\n"
        "TON\n"
        "Gift"
    )


@dp.message(SearchStates.query)
async def search_result(message: Message, state: FSMContext):
    query = message.text.strip()

    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("""
            SELECT id, name, amount, price
            FROM listings
            WHERE status='active'
            AND (
                name LIKE ?
                OR description LIKE ?
                OR category LIKE ?
            )
            ORDER BY id DESC
            LIMIT 20
        """, (
            f"%{query}%",
            f"%{query}%",
            f"%{query}%"
        ))

        rows = await cursor.fetchall()

    await state.clear()

    if not rows:
        await message.answer(
            f"🔎 По запросу «{query}» ничего не найдено."
        )
        return

    text = f"🔎 <b>РЕЗУЛЬТАТЫ:</b> {query}\n\n"
    buttons = []

    for lid, name, amount, price in rows:
        text += (
            f"#{lid} • {name}\n"
            f"{amount} • {price}\n\n"
        )

        buttons.append([
            InlineKeyboardButton(
                text=f"Открыть #{lid}",
                callback_data=f"listing_{lid}"
            )
        ])

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# =========================
# REPORT
# =========================

@dp.callback_query(F.data.startswith("report_"))
async def report_listing(callback: CallbackQuery):
    try:
        listing_id = int(callback.data.split("_")[1])
    except:
        await callback.answer("Ошибка")
        return

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            INSERT INTO reports
            (listing_id, reporter_id, reason, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            listing_id,
            callback.from_user.id,
            "Жалоба пользователя",
            datetime.now().isoformat()
        ))

        await db.commit()

    await callback.answer(
        "Жалоба отправлена.",
        show_alert=True
    )


# =========================
# HELP
# =========================

@dp.message(F.text == "🛡 Помощь")
async def help_message(message: Message):
    await message.answer(
        "🛡 <b>ПОМОЩЬ</b>\n\n"
        "🛒 Купить — просмотр объявлений\n"
        "📤 Продать — создать своё объявление\n"
        "🔎 Поиск — найти товар\n"
        "📋 Мои объявления — управление своими лотами\n"
        "🤝 Мои сделки — просмотр тестовых сделок\n"
        "👤 Профиль — статистика аккаунта\n\n"
        "Если нашёл подозрительное объявление — используй кнопку «Пожаловаться»."
    )


# =========================
# CANCEL
# =========================

@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "❌ Действие отменено.",
        reply_markup=main_keyboard()
    )


# =========================
# UNKNOWN
# =========================

@dp.message()
async def unknown(message: Message):
    await message.answer(
        "Используй кнопки меню 👇",
        reply_markup=main_keyboard()
    )


# =========================
# RUN
# =========================

async def main():
    await init_db()

    await bot.delete_webhook(drop_pending_updates=True)

    print("===================================")
    print("🌊 ATLANTIDA MARKET")
    print("🤖 BOT STARTED")
    print("===================================")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
