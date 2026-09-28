import asyncio
import logging
import os
from datetime import datetime

import aiosqlite
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в .env")

DB = "atlantida.db"

logging.basicConfig(level=logging.INFO)

bot = Bot(TOKEN)
dp = Dispatcher()


# =========================================================
# STATES
# =========================================================

class SellStates(StatesGroup):
    category = State()
    name = State()
    amount = State()
    price = State()
    description = State()


class SearchStates(StatesGroup):
    query = State()


# =========================================================
# DATABASE
# =========================================================

async def init_db():
    async with aiosqlite.connect(DB) as db:

        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
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
            amount REAL,
            price REAL,
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
            amount REAL,
            total_price REAL,
            status TEXT DEFAULT 'created',
            created_at TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER,
            reporter_id INTEGER,
            reason TEXT,
            status TEXT DEFAULT 'new',
            created_at TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER,
            from_user INTEGER,
            to_user INTEGER,
            rating INTEGER,
            comment TEXT,
            created_at TEXT
        )
        """)

        await db.commit()


async def add_user(user):
    async with aiosqlite.connect(DB) as db:

        await db.execute("""
        INSERT OR IGNORE INTO users
        (tg_id, username, first_name, created_at)
        VALUES (?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            datetime.now().isoformat()
        ))

        await db.execute("""
        UPDATE users
        SET username=?, first_name=?
        WHERE tg_id=?
        """, (
            user.username or "",
            user.first_name or "",
            user.id
        ))

        await db.commit()


# =========================================================
# KEYBOARDS
# =========================================================

def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🛒 Купить", callback_data="buy"),
                InlineKeyboardButton(text="📤 Продать", callback_data="sell")
            ],
            [
                InlineKeyboardButton(text="🔎 Поиск", callback_data="search"),
                InlineKeyboardButton(text="📋 Мои объявления", callback_data="my_listings")
            ],
            [
                InlineKeyboardButton(text="🤝 Мои сделки", callback_data="my_trades"),
                InlineKeyboardButton(text="👤 Профиль", callback_data="profile")
            ],
            [
                InlineKeyboardButton(text="🛡 Помощь", callback_data="help")
            ]
        ]
    )


def categories_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐ Stars", callback_data="cat_stars"),
                InlineKeyboardButton(text="🎁 Gifts", callback_data="cat_gifts")
            ],
            [
                InlineKeyboardButton(text="🖼 NFT", callback_data="cat_nft"),
                InlineKeyboardButton(text="💎 TON", callback_data="cat_ton")
            ],
            [
                InlineKeyboardButton(text="💰 Другое", callback_data="cat_other")
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")
            ]
        ]
    )


def back_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]
        ]
    )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):
    await add_user(message.from_user)

    text = (
        "🌊 <b>ATLANTIDA MARKET</b>\n\n"
        "Добро пожаловать в P2P-маркетплейс.\n\n"
        "Здесь пользователи могут создавать объявления "
        "и находить предложения других пользователей.\n\n"
        "⭐ Stars • 🎁 Gifts • 🖼 NFT • 💎 TON\n\n"
        "⚠️ Сделки сейчас работают в тестовом режиме.\n"
        "Бот не принимает и не хранит реальные средства.\n\n"
        "Выбери действие:"
    )

    await message.answer(
        text,
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


# =========================================================
# MENU
# =========================================================

@dp.callback_query(F.data == "menu")
async def menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    await callback.message.edit_text(
        "🌊 <b>ATLANTIDA MARKET</b>\n\n"
        "Главное меню:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# BUY / CATALOG
# =========================================================

async def show_catalog(callback: CallbackQuery, category=None):

    async with aiosqlite.connect(DB) as db:

        if category:
            cursor = await db.execute("""
            SELECT id, category, name, amount, price, description
            FROM listings
            WHERE status='active' AND category=?
            ORDER BY id DESC
            LIMIT 15
            """, (category,))
        else:
            cursor = await db.execute("""
            SELECT id, category, name, amount, price, description
            FROM listings
            WHERE status='active'
            ORDER BY id DESC
            LIMIT 15
            """)

        listings = await cursor.fetchall()

    if not listings:

        await callback.message.edit_text(
            "🛒 <b>Объявлений пока нет</b>\n\n"
            "Попробуй другую категорию или создай "
            "своё объявление.",
            reply_markup=back_menu(),
            parse_mode="HTML"
        )

        await callback.answer()
        return

    title = "🛒 <b>КАТАЛОГ</b>"

    if category:
        title += f"\n{category}"

    text = title + "\n\n"
    buttons = []

    for row in listings:
        lid, cat, name, amount, price, description = row

        text += (
            f"#{lid} • {cat}\n"
            f"📦 {name}\n"
            f"🔢 {amount:g}\n"
            f"💰 {price:g}\n"
        )

        if description:
            text += f"📝 {description[:70]}\n"

        text += "\n"

        buttons.append([
            InlineKeyboardButton(
                text=f"🔎 Открыть #{lid}",
                callback_data=f"listing_{lid}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="🔎 Фильтр", callback_data="categories")
    ])

    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")
    ])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(F.data == "buy")
async def buy(callback: CallbackQuery):
    await show_catalog(callback)


@dp.callback_query(F.data == "categories")
async def categories(callback: CallbackQuery):
    await callback.message.edit_text(
        "🏷 <b>ВЫБЕРИ КАТЕГОРИЮ</b>",
        reply_markup=categories_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


CATEGORY_MAP = {
    "cat_stars": "⭐ Stars",
    "cat_gifts": "🎁 Gifts",
    "cat_nft": "🖼 NFT",
    "cat_ton": "💎 TON",
    "cat_other": "💰 Другое"
}


@dp.callback_query(F.data.in_(CATEGORY_MAP.keys()))
async def category_catalog(callback: CallbackQuery):
    await show_catalog(callback, CATEGORY_MAP[callback.data])


# =========================================================
# OPEN LISTING
# =========================================================

@dp.callback_query(F.data.startswith("listing_"))
async def open_listing(callback: CallbackQuery):

    listing_id = int(callback.data.split("_")[1])

    async with aiosqlite.connect(DB) as db:

        cursor = await db.execute("""
        SELECT id, seller_id, category, name,
               amount, price, description, status
        FROM listings
        WHERE id=?
        """, (listing_id,))

        listing = await cursor.fetchone()

        if not listing:
            await callback.answer("Объявление не найдено", show_alert=True)
            return

        seller_id = listing[1]

        user_cursor = await db.execute("""
        SELECT username, first_name
        FROM users
        WHERE tg_id=?
        """, (seller_id,))

        seller = await user_cursor.fetchone()

        rating_cursor = await db.execute("""
        SELECT AVG(rating), COUNT(*)
        FROM reviews
        WHERE to_user=?
        """, (seller_id,))

        rating = await rating_cursor.fetchone()

    lid, seller_id, category, name, amount, price, description, status = listing

    if status != "active":
        await callback.answer("Объявление уже недоступно", show_alert=True)
        return

    seller_name = "не указан"

    if seller:
        seller_name = seller[0] or seller[1] or "пользователь"

    rating_text = "нет оценок"

    if rating and rating[1]:
        rating_text = f"{rating[0]:.1f}/5 ⭐ ({rating[1]})"

    text = (
        f"📦 <b>ОБЪЯВЛЕНИЕ #{lid}</b>\n\n"
        f"🏷 Категория: {category}\n"
        f"📌 Товар: {name}\n"
        f"🔢 Количество: {amount:g}\n"
        f"💰 Цена: {price:g}\n\n"
        f"👤 Продавец: @{seller_name.lstrip('@')}\n"
        f"⭐ Рейтинг: {rating_text}\n"
    )

    if description:
        text += f"\n📝 {description}\n"

    text += (
        "\n⚠️ Тестовый режим.\n"
        "Реальные средства бот не принимает и не хранит."
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
                text="⬅️ К каталогу",
                callback_data="buy"
            )
        ]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# CREATE TEST DEAL
# =========================================================

@dp.callback_query(F.data.startswith("deal_"))
async def create_deal(callback: CallbackQuery):

    listing_id = int(callback.data.split("_")[1])

    async with aiosqlite.connect(DB) as db:

        cursor = await db.execute("""
        SELECT seller_id, amount, price, status
        FROM listings
        WHERE id=?
        """, (listing_id,))

        listing = await cursor.fetchone()

        if not listing:
            await callback.answer("Объявление не найдено", show_alert=True)
            return

        seller_id, amount, price, status = listing

        if status != "active":
            await callback.answer("Объявление уже закрыто", show_alert=True)
            return

        if seller_id == callback.from_user.id:
            await callback.answer(
                "Нельзя купить своё объявление",
                show_alert=True
            )
            return

        await db.execute("""
        INSERT INTO trades
        (listing_id, buyer_id, seller_id, amount,
         total_price, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            listing_id,
            callback.from_user.id,
            seller_id,
            amount,
            price,
            "created",
            datetime.now().isoformat()
        ))

        await db.execute("""
        UPDATE listings
        SET status='reserved'
        WHERE id=?
        """, (listing_id,))

        await db.commit()

    await callback.message.edit_text(
        "🤝 <b>СДЕЛКА СОЗДАНА</b>\n\n"
        f"Объявление: #{listing_id}\n"
        f"Количество: {amount:g}\n"
        f"Сумма: {price:g}\n\n"
        "📌 Статус: создана\n\n"
        "⚠️ Это тестовый режим.\n"
        "Реальные средства бот не принимает и не хранит.",
        reply_markup=back_menu(),
        parse_mode="HTML"
    )

    await callback.answer("Сделка создана")


# =========================================================
# SELL
# =========================================================

@dp.callback_query(F.data == "sell")
async def sell(callback: CallbackQuery, state: FSMContext):

    await state.set_state(SellStates.category)

    await callback.message.edit_text(
        "📤 <b>СОЗДАНИЕ ОБЪЯВЛЕНИЯ</b>\n\n"
        "Выбери категорию:",
        reply_markup=categories_keyboard(),
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(
    SellStates.category,
    F.data.in_(CATEGORY_MAP.keys())
)
async def choose_category(callback: CallbackQuery, state: FSMContext):

    category = CATEGORY_MAP[callback.data]

    await state.update_data(category=category)
    await state.set_state(SellStates.name)

    await callback.message.edit_text(
        f"✅ Категория: <b>{category}</b>\n\n"
        "Напиши название товара.\n\n"
        "Например:\n"
        "• 100 Telegram Stars\n"
        "• Bear Gift\n"
        "• NFT #12345\n"
        "• 10 TON\n\n"
        "Для отмены используй /cancel",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.message(SellStates.name)
async def sell_name(message: Message, state: FSMContext):

    name = (message.text or "").strip()

    if len(name) < 2:
        await message.answer("❌ Название слишком короткое.")
        return

    if len(name) > 100:
        await message.answer("❌ Название максимум 100 символов.")
        return

    await state.update_data(name=name)
    await state.set_state(SellStates.amount)

    await message.answer(
        "🔢 Напиши количество товара.\n\n"
        "Например: <code>100</code>",
        parse_mode="HTML"
    )


@dp.message(SellStates.amount)
async def sell_amount(message: Message, state: FSMContext):

    try:
        amount = float((message.text or "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число. Например: <code>100</code>",
                             parse_mode="HTML")
        return

    if amount <= 0:
        await message.answer("❌ Количество должно быть больше нуля.")
        return

    await state.update_data(amount=amount)
    await state.set_state(SellStates.price)

    await message.answer(
        "💰 Напиши цену всего объявления.\n\n"
        "Например: <code>150</code>",
        parse_mode="HTML"
    )


@dp.message(SellStates.price)
async def sell_price(message: Message, state: FSMContext):

    try:
        price = float((message.text or "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число. Например: <code>150</code>",
                             parse_mode="HTML")
        return

    if price <= 0:
        await message.answer("❌ Цена должна быть больше нуля.")
        return

    await state.update_data(price=price)
    await state.set_state(SellStates.description)

    await message.answer(
        "📝 Напиши описание объявления.\n\n"
        "Укажи дополнительные условия или детали.\n\n"
        "Если описание не нужно — отправь <code>-</code>.",
        parse_mode="HTML"
    )


@dp.message(SellStates.description)
async def sell_description(message: Message, state: FSMContext):

    description = (message.text or "").strip()

    if description == "-":
        description = ""

    if len(description) > 1000:
        await message.answer("❌ Описание максимум 1000 символов.")
        return

    data = await state.get_data()

    async with aiosqlite.connect(DB) as db:

        cursor = await db.execute("""
        INSERT INTO listings
        (seller_id, category, name, amount, price,
         description, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            message.from_user.id,
            data["category"],
            data["name"],
            data["amount"],
            data["price"],
            description,
            "active",
            datetime.now().isoformat()
        ))

        listing_id = cursor.lastrowid

        await db.commit()

    await state.clear()

    await message.answer(
        "✅ <b>ОБЪЯВЛЕНИЕ СОЗДАНО!</b>\n\n"
        f"🆔 ID: #{listing_id}\n"
        f"🏷 {data['category']}\n"
        f"📦 {data['name']}\n"
        f"🔢 Количество: {data['amount']:g}\n"
        f"💰 Цена: {data['price']:g}\n\n"
        "Теперь его увидят покупатели.",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


# =========================================================
# MY LISTINGS
# =========================================================

@dp.callback_query(F.data == "my_listings")
async def my_listings(callback: CallbackQuery):

    async with aiosqlite.connect(DB) as db:

        cursor = await db.execute("""
        SELECT id, category, name, amount, price, status
        FROM listings
        WHERE seller_id=?
        ORDER BY id DESC
        """, (callback.from_user.id,))

        rows = await cursor.fetchall()

    if not rows:
        await callback.message.edit_text(
            "📋 <b>МОИ ОБЪЯВЛЕНИЯ</b>\n\n"
            "У тебя пока нет объявлений.",
            reply_markup=back_menu(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    text = "📋 <b>МОИ ОБЪЯВЛЕНИЯ</b>\n\n"
    buttons = []

    status_text = {
        "active": "🟢 активно",
        "reserved": "🟡 резерв",
        "closed": "⚫ закрыто"
    }

    for row in rows:

        lid, category, name, amount, price, status = row

        text += (
            f"#{lid} • {category}\n"
            f"📦 {name}\n"
            f"🔢 {amount:g}\n"
            f"💰 {price:g}\n"
            f"{status_text.get(status, status)}\n\n"
        )

        if status == "active":
            buttons.append([
                InlineKeyboardButton(
                    text=f"❌ Закрыть #{lid}",
                    callback_data=f"close_{lid}"
                )
            ])

    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")
    ])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("close_"))
async def close_listing(callback: CallbackQuery):

    listing_id = int(callback.data.split("_")[1])

    async with aiosqlite.connect(DB) as db:

        await db.execute("""
        UPDATE listings
        SET status='closed'
        WHERE id=? AND seller_id=? AND status='active'
        """, (
            listing_id,
            callback.from_user.id
        ))

        await db.commit()

    await callback.answer("Объявление закрыто", show_alert=True)

    await my_listings(callback)


# =========================================================
# MY TRADES
# =========================================================

@dp.callback_query(F.data == "my_trades")
async def my_trades(callback: CallbackQuery):

    async with aiosqlite.connect(DB) as db:

        cursor = await db.execute("""
        SELECT id, listing_id, amount, total_price, status
        FROM trades
        WHERE buyer_id=? OR seller_id=?
        ORDER BY id DESC
        """, (
            callback.from_user.id,
            callback.from_user.id
        ))

        rows = await cursor.fetchall()

    if not rows:
        await callback.message.edit_text(
            "🤝 <b>МОИ СДЕЛКИ</b>\n\n"
            "Сделок пока нет.",
            reply_markup=back_menu(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    text = "🤝 <b>МОИ СДЕЛКИ</b>\n\n"

    for row in rows:

        trade_id, listing_id, amount, price, status = row

        text += (
            f"🆔 Сделка #{trade_id}\n"
            f"📦 Объявление #{listing_id}\n"
            f"🔢 Количество: {amount:g}\n"
            f"💰 Сумма: {price:g}\n"
            f"📌 Статус: {status}\n\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=back_menu(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# PROFILE
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):

    async with aiosqlite.connect(DB) as db:

        cursor = await db.execute("""
        SELECT COUNT(*)
        FROM listings
        WHERE seller_id=?
        """, (callback.from_user.id,))

        listings_count = (await cursor.fetchone())[0]

        cursor = await db.execute("""
        SELECT COUNT(*)
        FROM trades
        WHERE buyer_id=? OR seller_id=?
        """, (
            callback.from_user.id,
            callback.from_user.id
        ))

        trades_count = (await cursor.fetchone())[0]

        cursor = await db.execute("""
        SELECT AVG(rating), COUNT(*)
        FROM reviews
        WHERE to_user=?
        """, (callback.from_user.id,))

        rating = await cursor.fetchone()

    username = (
        f"@{callback.from_user.username}"
        if callback.from_user.username
        else "не указан"
    )

    if rating and rating[1]:
        rating_text = f"{rating[0]:.1f}/5 ⭐ ({rating[1]} отзывов)"
    else:
        rating_text = "нет оценок"

    text = (
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        f"🆔 ID: <code>{callback.from_user.id}</code>\n"
        f"👤 Username: {username}\n\n"
        f"📋 Объявлений: {listings_count}\n"
        f"🤝 Сделок: {trades_count}\n"
        f"⭐ Рейтинг: {rating_text}\n\n"
        "🌊 ATLANTIDA MARKET"
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_menu(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# SEARCH
# =========================================================

@dp.callback_query(F.data == "search")
async def search_start(callback: CallbackQuery, state: FSMContext):

    await state.set_state(SearchStates.query)

    await callback.message.edit_text(
        "🔎 <b>ПОИСК</b>\n\n"
        "Напиши название товара или категорию.\n\n"
        "Например:\n"
        "<code>Stars</code>\n"
        "<code>Bear</code>\n"
        "<code>NFT</code>",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.message(SearchStates.query)
async def search_result(message: Message, state: FSMContext):

    query = (message.text or "").strip()

    if len(query) < 2:
        await message.answer("❌ Напиши хотя бы 2 символа.")
        return

    await state.clear()

    async with aiosqlite.connect(DB) as db:

        cursor = await db.execute("""
        SELECT id, category, name, amount, price
        FROM listings
        WHERE status='active'
        AND (
            name LIKE ?
            OR category LIKE ?
            OR description LIKE ?
        )
        ORDER BY id DESC
        LIMIT 15
        """, (
            f"%{query}%",
            f"%{query}%",
            f"%{query}%"
        ))

        rows = await cursor.fetchall()

    if not rows:

        await message.answer(
            f"🔎 По запросу <b>{query}</b> ничего не найдено.",
            reply_markup=main_menu(),
            parse_mode="HTML"
        )
        return

    text = f"🔎 <b>РЕЗУЛЬТАТЫ: {query}</b>\n\n"
    buttons = []

    for row in rows:

        lid, category, name, amount, price = row

        text += (
            f"#{lid} • {category}\n"
            f"📦 {name}\n"
            f"🔢 {amount:g}\n"
            f"💰 {price:g}\n\n"
        )

        buttons.append([
            InlineKeyboardButton(
                text=f"🔎 Открыть #{lid}",
                callback_data=f"listing_{lid}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")
    ])

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


# =========================================================
# REPORTS
# =========================================================

@dp.callback_query(F.data.startswith("report_"))
async def report_listing(callback: CallbackQuery):

    listing_id = int(callback.data.split("_")[1])

    async with aiosqlite.connect(DB) as db:

        cursor = await db.execute("""
        SELECT id
        FROM listings
        WHERE id=?
        """, (listing_id,))

        exists = await cursor.fetchone()

        if not exists:
            await callback.answer(
                "Объявление не найдено",
                show_alert=True
            )
            return

        await db.execute("""
        INSERT INTO reports
        (listing_id, reporter_id, reason, created_at)
        VALUES (?, ?, ?, ?)
        """, (
            listing_id,
            callback.from_user.id,
            "Пользователь пожаловался на объявление",
            datetime.now().isoformat()
        ))

        await db.commit()

    await callback.answer(
        "Жалоба отправлена администрации",
        show_alert=True
    )


# =========================================================
# HELP
# =========================================================

@dp.callback_query(F.data == "help")
async def help_menu(callback: CallbackQuery):

    text = (
        "🛡 <b>ПОМОЩЬ</b>\n\n"
        "🌊 <b>Atlantida Market</b> — тестовый P2P-маркетплейс.\n\n"
        "📤 Продать — создать объявление.\n"
        "🛒 Купить — посмотреть предложения.\n"
        "🔎 Поиск — найти товар.\n"
        "📋 Мои объявления — управление своими объявлениями.\n"
        "🤝 Мои сделки — история тестовых сделок.\n"
        "👤 Профиль — информация о пользователе.\n\n"
        "⚠️ Сейчас бот не принимает, не хранит и не переводит "
        "реальные криптоактивы или деньги."
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_menu(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# CANCEL
# =========================================================

@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):

    await state.clear()

    await message.answer(
        "❌ Действие отменено.",
        reply_markup=main_menu()
    )


# =========================================================
# ADMIN
# =========================================================

ADMIN_IDS = set()

admin_env = os.getenv("ADMIN_IDS", "")

if admin_env:
    for item in admin_env.split(","):
        item = item.strip()
        if item.isdigit():
            ADMIN_IDS.add(int(item))


def is_admin(user_id):
    return user_id in ADMIN_IDS


@dp.message(Command("admin"))
async def admin(message: Message):

    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    async with aiosqlite.connect(DB) as db:

        cursor = await db.execute("SELECT COUNT(*) FROM users")
        users = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM listings")
        listings = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM trades")
        trades = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM reports WHERE status='new'")
        reports = (await cursor.fetchone())[0]

    await message.answer(
        "👑 <b>ADMIN PANEL</b>\n\n"
        f"👥 Пользователей: {users}\n"
        f"📋 Объявлений: {listings}\n"
        f"🤝 Сделок: {trades}\n"
        f"🚨 Новых жалоб: {reports}",
        parse_mode="HTML"
    )


# =========================================================
# UNKNOWN COMMAND
# =========================================================

@dp.message(Command("menu"))
async def command_menu(message: Message, state: FSMContext):

    await state.clear()

    await message.answer(
        "🌊 <b>ATLANTIDA MARKET</b>\n\nГлавное меню:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


# =========================================================
# RUN
# =========================================================

async def main():

    await init_db()

    print("===================================")
    print("🌊 ATLANTIDA MARKET")
    print("🤖 BOT STARTED")
    print("===================================")

    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types()
    )


if __name__ == "__main__":
    asyncio.run(main())
