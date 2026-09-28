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
    WebAppInfo,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в .env")

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "atlantida.db")


CATEGORIES = {
    "stars": "⭐ Stars",
    "gifts": "🎁 Gifts",
    "nft": "💎 NFT",
    "ton": "💠 TON",
    "crypto": "🪙 Crypto",
    "other": "📦 Другое",
}


class SellStates(StatesGroup):
    category = State()
    name = State()
    amount = State()
    price = State()
    description = State()


class SearchStates(StatesGroup):
    query = State()


async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            created_at TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS listings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER,
            category TEXT,
            name TEXT,
            amount TEXT,
            price TEXT,
            description TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT,
            currency TEXT DEFAULT 'TON'
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER,
            buyer_id INTEGER,
            seller_id INTEGER,
            amount TEXT DEFAULT '',
            currency TEXT DEFAULT 'TON',
            status TEXT DEFAULT 'pending',
            tx_hash TEXT DEFAULT '',
            created_at TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reviews(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER,
            buyer_id INTEGER,
            rating INTEGER,
            text TEXT,
            created_at TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER,
            reporter_id INTEGER,
            reason TEXT,
            created_at TEXT
        )
        """)

        await db.commit()


async def save_user(user):
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        INSERT INTO users
        (id,username,first_name,created_at)
        VALUES(?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            datetime.utcnow().isoformat()
        ))
        await db.commit()


def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="🛒 Купить",
                    web_app=WebAppInfo(
                        url="https://atlantidamarket.onrender.com/"
                    )
                ),
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


def categories_keyboard(prefix):
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


@dp.message(CommandStart())
async def start(message: Message):
    await save_user(message.from_user)

    await message.answer(
        "🌊 <b>ATLANTIDA MARKET</b>\n\n"
        "Маркетплейс цифровых товаров.\n\n"
        "🛒 Покупай\n"
        "📤 Продавай\n"
        "🔎 Ищи товары\n"
        "🤝 Управляй сделками\n"
        "⭐ Получай отзывы\n\n"
        "Открой меню ниже 👇",
        reply_markup=main_keyboard()
    )


@dp.message(Command("menu"))
async def menu(message: Message):
    await message.answer(
        "🌊 <b>ATLANTIDA MARKET</b>\n\nВыбери действие:",
        reply_markup=main_keyboard()
    )


@dp.message(F.text == "🛒 Купить")
async def buy(message: Message):
    await message.answer(
        "🛒 <b>КАТАЛОГ</b>\n\nВыбери категорию:",
        reply_markup=categories_keyboard("filter")
    )


async def category_text(category, limit=20):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT id,name,amount,price,currency
        FROM listings
        WHERE category=? AND status='active'
        ORDER BY id DESC
        LIMIT ?
        """, (category, limit))

        return await cur.fetchall()


@dp.callback_query(F.data.startswith("filter_"))
async def filter_category(callback: CallbackQuery):
    category = callback.data.replace("filter_", "")

    if category not in CATEGORIES:
        await callback.answer("Ошибка")
        return

    rows = await category_text(category)

    if not rows:
        await callback.message.edit_text(
            f"{CATEGORIES[category]}\n\n"
            "Пока здесь нет активных объявлений.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Категории",
                            callback_data="buy_back"
                        )
                    ]
                ]
            )
        )
        await callback.answer()
        return

    text = f"{CATEGORIES[category]}\n\n"
    buttons = []

    for lid, name, amount, price, currency in rows:
        text += (
            f"#{lid} • <b>{name}</b>\n"
            f"{amount} • {price} {currency}\n\n"
        )

        buttons.append([
            InlineKeyboardButton(
                text=f"🔎 Открыть #{lid}",
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


@dp.callback_query(F.data == "buy_back")
async def buy_back(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛒 <b>КАТАЛОГ</b>\n\nВыбери категорию:",
        reply_markup=categories_keyboard("filter")
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("listing_"))
async def listing_details(callback: CallbackQuery):
    try:
        listing_id = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer("Ошибка")
        return

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT
            l.id,l.seller_id,l.category,l.name,l.amount,
            l.price,l.description,l.currency,u.username
        FROM listings l
        LEFT JOIN users u ON u.id=l.seller_id
        WHERE l.id=?
        """, (listing_id,))

        row = await cur.fetchone()

    if not row:
        await callback.answer(
            "Объявление не найдено",
            show_alert=True
        )
        return

    (
        lid,seller_id,category,name,amount,
        price,description,currency,username
    ) = row

    text = (
        f"💎 <b>ОБЪЯВЛЕНИЕ #{lid}</b>\n\n"
        f"Категория: {CATEGORIES.get(category, category)}\n"
        f"Название: <b>{name}</b>\n"
        f"Количество: {amount}\n"
        f"Цена: <b>{price} {currency}</b>\n\n"
        f"Описание:\n{description or 'Без описания'}\n\n"
        f"👤 Продавец: "
        f"{('@' + username) if username else 'скрыт'}"
    )

    buttons = [
        [
            InlineKeyboardButton(
                text="🤝 Создать сделку",
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
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("deal_"))
async def create_deal(callback: CallbackQuery):
    try:
        listing_id = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer("Ошибка")
        return

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT seller_id,price,currency,status
        FROM listings
        WHERE id=?
        """, (listing_id,))

        row = await cur.fetchone()

        if not row:
            await callback.answer(
                "Объявление не найдено",
                show_alert=True
            )
            return

        seller_id,price,currency,status = row

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

        cur = await db.execute("""
        INSERT INTO trades
        (listing_id,buyer_id,seller_id,amount,currency,status,created_at)
        VALUES(?,?,?,?,?,?,?)
        """, (
            listing_id,
            callback.from_user.id,
            seller_id,
            str(price),
            currency or "TON",
            "pending",
            datetime.utcnow().isoformat()
        ))

        trade_id = cur.lastrowid
        await db.commit()

    await callback.message.answer(
        "🤝 <b>СДЕЛКА СОЗДАНА</b>\n\n"
        f"Номер сделки: #{trade_id}\n"
        f"Объявление: #{listing_id}\n"
        f"Сумма: {price} {currency}\n\n"
        "Статус: ⏳ ожидается оплата."
    )

    try:
        await bot.send_message(
            seller_id,
            "🔔 <b>Новая сделка</b>\n\n"
            f"По вашему объявлению #{listing_id} "
            f"создана сделка #{trade_id}."
        )
    except Exception:
        pass

    await callback.answer("Сделка создана")


@dp.callback_query(F.data.startswith("report_"))
async def report_listing(callback: CallbackQuery):
    try:
        listing_id = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer("Ошибка")
        return

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        INSERT INTO reports
        (listing_id,reporter_id,reason,created_at)
        VALUES(?,?,?,?)
        """, (
            listing_id,
            callback.from_user.id,
            "Жалоба пользователя",
            datetime.utcnow().isoformat()
        ))
        await db.commit()

    await callback.answer(
        "Жалоба отправлена.",
        show_alert=True
    )


@dp.message(F.text == "📤 Продать")
async def sell(message: Message, state: FSMContext):
    await state.set_state(SellStates.category)

    buttons = []

    for key,name in CATEGORIES.items():
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
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.callback_query(
    F.data.startswith("sellcat_"),
    SellStates.category
)
async def sell_category(
    callback: CallbackQuery,
    state: FSMContext
):
    category = callback.data.replace("sellcat_", "")

    if category not in CATEGORIES:
        await callback.answer("Ошибка")
        return

    await state.update_data(category=category)
    await state.set_state(SellStates.name)

    await callback.message.answer(
        "✏️ Введи название товара."
    )
    await callback.answer()


@dp.message(SellStates.name)
async def sell_name(
    message: Message,
    state: FSMContext
):
    await state.update_data(name=message.text.strip())
    await state.set_state(SellStates.amount)

    await message.answer(
        "🔢 Введи количество.\n\n"
        "Например: 100"
    )


@dp.message(SellStates.amount)
async def sell_amount(
    message: Message,
    state: FSMContext
):
    await state.update_data(amount=message.text.strip())
    await state.set_state(SellStates.price)

    await message.answer(
        "💰 Введи цену.\n\n"
        "Например: 5 TON"
    )


@dp.message(SellStates.price)
async def sell_price(
    message: Message,
    state: FSMContext
):
    await state.update_data(price=message.text.strip())
    await state.set_state(SellStates.description)

    await message.answer(
        "📝 Напиши описание товара.\n\n"
        "Если описания нет — напиши «нет»."
    )


@dp.message(SellStates.description)
async def sell_description(
    message: Message,
    state: FSMContext
):
    data = await state.get_data()

    description = message.text.strip()

    if description.lower() == "нет":
        description = ""

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        INSERT INTO listings
        (seller_id,category,name,amount,price,description,status,created_at)
        VALUES(?,?,?,?,?,?,?,?)
        """, (
            message.from_user.id,
            data["category"],
            data["name"],
            data["amount"],
            data["price"],
            description,
            "active",
            datetime.utcnow().isoformat()
        ))

        listing_id = cur.lastrowid
        await db.commit()

    await state.clear()

    await message.answer(
        "✅ <b>ОБЪЯВЛЕНИЕ СОЗДАНО</b>\n\n"
        f"Номер: #{listing_id}\n"
        f"Товар: {data['name']}\n"
        f"Количество: {data['amount']}\n"
        f"Цена: {data['price']}\n\n"
        "Объявление опубликовано.",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "cancel_sell")
async def cancel_sell(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.clear()

    await callback.message.answer(
        "❌ Создание объявления отменено.",
        reply_markup=main_keyboard()
    )

    await callback.answer()


@dp.message(F.text == "📋 Мои объявления")
async def my_listings(message: Message):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT id,name,amount,price,status
        FROM listings
        WHERE seller_id=?
        ORDER BY id DESC
        """, (message.from_user.id,))

        rows = await cur.fetchall()

    if not rows:
        await message.answer(
            "📋 У тебя пока нет объявлений."
        )
        return

    text = "📋 <b>МОИ ОБЪЯВЛЕНИЯ</b>\n\n"
    buttons = []

    for lid,name,amount,price,status in rows:
        status_text = (
            "🟢 активно"
            if status == "active"
            else "🔴 закрыто"
        )

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
        reply_markup=(
            InlineKeyboardMarkup(inline_keyboard=buttons)
            if buttons else None
        )
    )


@dp.callback_query(F.data.startswith("close_"))
async def close_listing(callback: CallbackQuery):
    try:
        listing_id = int(callback.data.split("_")[1])
    except Exception:
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


@dp.message(F.text == "🤝 Мои сделки")
async def my_trades(message: Message):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT
            id,listing_id,buyer_id,seller_id,
            amount,currency,status
        FROM trades
        WHERE buyer_id=? OR seller_id=?
        ORDER BY id DESC
        """, (
            message.from_user.id,
            message.from_user.id
        ))

        rows = await cur.fetchall()

    if not rows:
        await message.answer(
            "🤝 У тебя пока нет сделок."
        )
        return

    names = {
        "pending": "⏳ Ожидает оплаты",
        "paid": "💳 Оплачено",
        "delivered": "📦 Товар передан",
        "completed": "✅ Завершено",
        "cancelled": "❌ Отменено"
    }

    text = "🤝 <b>МОИ СДЕЛКИ</b>\n\n"

    for row in rows:
        tid,lid,buyer,seller,amount,currency,status = row

        role = (
            "Покупатель"
            if buyer == message.from_user.id
            else "Продавец"
        )

        text += (
            f"<b>Сделка #{tid}</b>\n"
            f"Объявление: #{lid}\n"
            f"Роль: {role}\n"
            f"Сумма: {amount} {currency}\n"
            f"Статус: {names.get(status,status)}\n\n"
        )

    await message.answer(text)


@dp.message(F.text == "👤 Профиль")
async def profile(message: Message):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT COUNT(*)
        FROM listings
        WHERE seller_id=?
        """, (message.from_user.id,))

        listings_count = (await cur.fetchone())[0]

        cur = await db.execute("""
        SELECT COUNT(*)
        FROM trades
        WHERE buyer_id=? OR seller_id=?
        """, (
            message.from_user.id,
            message.from_user.id
        ))

        trades_count = (await cur.fetchone())[0]

        cur = await db.execute("""
        SELECT AVG(rating),COUNT(*)
        FROM reviews
        WHERE seller_id=?
        """, (message.from_user.id,))

        rating,reviews_count = await cur.fetchone()

    rating_text = (
        f"{rating:.1f}/5"
        if rating else "нет оценок"
    )

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "не указан"
    )

    await message.answer(
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        f"ID: <code>{message.from_user.id}</code>\n"
        f"Username: {username}\n\n"
        f"📋 Объявлений: {listings_count}\n"
        f"🤝 Сделок: {trades_count}\n"
        f"⭐ Рейтинг: {rating_text}\n"
        f"💬 Отзывов: {reviews_count}"
    )


@dp.message(F.text == "🔎 Поиск")
async def search_start(
    message: Message,
    state: FSMContext
):
    await state.set_state(SearchStates.query)

    await message.answer(
        "🔎 <b>ПОИСК</b>\n\n"
        "Напиши название товара.\n\n"
        "Например: Stars, NFT, TON, Gift"
    )


@dp.message(SearchStates.query)
async def search_result(
    message: Message,
    state: FSMContext
):
    query = message.text.strip()

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT id,name,amount,price
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

        rows = await cur.fetchall()

    await state.clear()

    if not rows:
        await message.answer(
            f"🔎 По запросу «{query}» ничего не найдено."
        )
        return

    text = f"🔎 <b>РЕЗУЛЬТАТЫ:</b> {query}\n\n"
    buttons = []

    for lid,name,amount,price in rows:
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
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.message(F.text == "🛡 Помощь")
async def help_message(message: Message):
    await message.answer(
        "🛡 <b>ПОМОЩЬ</b>\n\n"
        "🛒 Купить — каталог товаров\n"
        "📤 Продать — создать объявление\n"
        "🔎 Поиск — найти товар\n"
        "📋 Мои объявления — управление товарами\n"
        "🤝 Мои сделки — управление сделками\n"
        "👤 Профиль — статистика аккаунта\n\n"
        "Если заметил подозрительное объявление — "
        "используй кнопку «Пожаловаться»."
    )


@dp.message(Command("cancel"))
async def cancel(
    message: Message,
    state: FSMContext
):
    await state.clear()

    await message.answer(
        "❌ Действие отменено.",
        reply_markup=main_keyboard()
    )


@dp.message()
async def unknown(message: Message):
    await message.answer(
        "Используй кнопки меню 👇",
        reply_markup=main_keyboard()
    )


async def main():
    await init_db()

    await bot.delete_webhook(
        drop_pending_updates=True
    )

    print("===================================")
    print("🌊 ATLANTIDA MARKET")
    print("🤖 BOT STARTED")
    print("===================================")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
