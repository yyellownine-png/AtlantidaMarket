import asyncio
import os
from datetime import datetime
import json

import aiosqlite
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в .env")

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")
DB = os.path.join(BASE, "atlantida.db")


async def db_columns(db, table):
    cur = await db.execute(f"PRAGMA table_info({table})")
    return [x[1] for x in await cur.fetchall()]


async def add_column(db, table, column, definition):
    cols = await db_columns(db, table)
    if column not in cols:
        await db.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


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
            seller_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            amount TEXT DEFAULT '1',
            price TEXT NOT NULL,
            description TEXT DEFAULT '',
            currency TEXT DEFAULT 'TON',
            status TEXT DEFAULT 'active',
            created_at TEXT
        )
        """)

        await add_column(db, "listings", "currency", "TEXT DEFAULT 'TON'")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            amount TEXT DEFAULT '',
            currency TEXT DEFAULT 'TON',
            status TEXT DEFAULT 'pending',
            tx_hash TEXT DEFAULT '',
            created_at TEXT
        )
        """)

        await add_column(db, "trades", "amount", "TEXT DEFAULT ''")
        await add_column(db, "trades", "currency", "TEXT DEFAULT 'TON'")
        await add_column(db, "trades", "tx_hash", "TEXT DEFAULT ''")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS seller_payment_methods(
            seller_id INTEGER PRIMARY KEY,
            crypto_send TEXT DEFAULT '',
            ton_wallet TEXT DEFAULT '',
            usdt_wallet TEXT DEFAULT '',
            card_info TEXT DEFAULT '',
            updated_at TEXT
        )
        """)

        await add_column(
            db, "seller_payment_methods",
            "usdt_wallet", "TEXT DEFAULT ''"
        )

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reviews(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            text TEXT DEFAULT '',
            created_at TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL,
            reporter_id INTEGER NOT NULL,
            reason TEXT DEFAULT '',
            created_at TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS public_chat(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            photo_url TEXT DEFAULT '',
            text TEXT NOT NULL,
            created_at TEXT
        )
        """)

        await db.commit()


async def json_body(request):
    try:
        return await request.json()
    except Exception:
        return {}


async def index(request):
    return web.FileResponse(os.path.join(WEB, "index.html"))


async def listings(request):
    category = request.query.get("category", "Все")
    search = request.query.get("search", "").strip()

    async with aiosqlite.connect(DB) as db:
        query = """
        SELECT
            l.id,l.seller_id,l.category,l.name,l.amount,
            l.price,l.description,l.currency,l.created_at,
            u.username,u.first_name
        FROM listings l
        LEFT JOIN users u ON u.id=l.seller_id
        WHERE l.status='active'
        """
        args = []

        if category and category != "Все":
            query += " AND l.category=?"
            args.append(category)

        if search:
            query += """
            AND (
                l.name LIKE ?
                OR l.description LIKE ?
                OR l.category LIKE ?
            )
            """
            q = f"%{search}%"
            args.extend([q, q, q])

        query += " ORDER BY l.id DESC LIMIT 100"

        cur = await db.execute(query, args)
        rows = await cur.fetchall()

    result = []
    for r in rows:
        result.append({
            "id": r[0],
            "seller_id": r[1],
            "category": r[2],
            "name": r[3],
            "title": r[3],
            "amount": r[4],
            "price": r[5],
            "description": r[6] or "",
            "currency": r[7] or "TON",
            "created_at": r[8],
            "seller_username": r[9] or "",
            "seller_name": r[10] or "Пользователь"
        })

    return web.json_response({"ok": True, "listings": result})


async def create_listing(request):
    data = await json_body(request)

    seller_id = int(data.get("seller_id", 0))
    name = str(data.get("name") or data.get("title") or "").strip()
    category = str(data.get("category") or "Другое").strip()
    amount = str(data.get("amount") or "1").strip()
    price = str(data.get("price") or "").strip()
    currency = str(data.get("currency") or "TON").upper().strip()
    description = str(data.get("description") or "").strip()

    if not seller_id or not name or not price:
        return web.json_response(
            {"ok": False, "error": "Заполни название и цену"},
            status=400
        )

    if currency not in ("TON", "USDT", "STARS"):
        return web.json_response(
            {"ok": False, "error": "Недопустимая валюта"},
            status=400
        )

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        INSERT INTO users(id,username,first_name,created_at)
        VALUES(?,?,?,?)
        ON CONFLICT(id) DO NOTHING
        """, (seller_id, "", "Пользователь", datetime.utcnow().isoformat()))

        cur = await db.execute("""
        INSERT INTO listings
        (seller_id,category,name,amount,price,description,currency,status,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        """, (
            seller_id, category, name, amount, price,
            description, currency, "active",
            datetime.utcnow().isoformat()
        ))
        listing_id = cur.lastrowid
        await db.commit()

    return web.json_response({"ok": True, "id": listing_id})


async def close_listing(request):
    data = await json_body(request)
    listing_id = int(data.get("listing_id", 0))
    user_id = int(data.get("user_id", 0))

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        UPDATE listings
        SET status='closed'
        WHERE id=? AND seller_id=? AND status='active'
        """, (listing_id, user_id))
        await db.commit()

    if cur.rowcount == 0:
        return web.json_response(
            {"ok": False, "error": "Объявление не найдено"},
            status=404
        )

    return web.json_response({"ok": True})


async def payment_methods(request):
    seller_id = int(request.match_info["seller_id"])

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT ton_wallet,usdt_wallet
        FROM seller_payment_methods
        WHERE seller_id=?
        """, (seller_id,))
        row = await cur.fetchone()

    if not row:
        return web.json_response({
            "ok": True,
            "ton_wallet": "",
            "usdt_wallet": "",
            "connected": False
        })

    return web.json_response({
        "ok": True,
        "ton_wallet": row[0] or "",
        "usdt_wallet": row[1] or "",
        "connected": bool(row[0] or row[1])
    })


async def save_payment_methods(request):
    data = await json_body(request)

    seller_id = int(data.get("seller_id", 0))
    ton = str(data.get("ton_wallet") or "").strip()
    usdt = str(data.get("usdt_wallet") or "").strip()

    if not seller_id:
        return web.json_response(
            {"ok": False, "error": "Неизвестный пользователь"},
            status=400
        )

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        INSERT INTO seller_payment_methods
        (seller_id,ton_wallet,usdt_wallet,updated_at)
        VALUES(?,?,?,?)
        ON CONFLICT(seller_id) DO UPDATE SET
            ton_wallet=excluded.ton_wallet,
            usdt_wallet=excluded.usdt_wallet,
            updated_at=excluded.updated_at
        """, (
            seller_id, ton, usdt,
            datetime.utcnow().isoformat()
        ))
        await db.commit()

    return web.json_response({"ok": True})


async def create_trade(request):
    data = await json_body(request)

    listing_id = int(data.get("listing_id", 0))
    buyer_id = int(data.get("buyer_id", 0))

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT seller_id,price,currency,name,status
        FROM listings
        WHERE id=?
        """, (listing_id,))
        listing = await cur.fetchone()

        if not listing:
            return web.json_response(
                {"ok": False, "error": "Объявление не найдено"},
                status=404
            )

        seller_id, price, currency, name, status = listing

        if seller_id == buyer_id:
            return web.json_response(
                {"ok": False, "error": "Нельзя купить своё объявление"},
                status=400
            )

        if status != "active":
            return web.json_response(
                {"ok": False, "error": "Объявление уже закрыто"},
                status=400
            )

        cur = await db.execute("""
        INSERT INTO trades
        (listing_id,buyer_id,seller_id,amount,currency,status,created_at)
        VALUES(?,?,?,?,?,?,?)
        """, (
            listing_id,
            buyer_id,
            seller_id,
            str(price),
            str(currency or "TON"),
            "pending",
            datetime.utcnow().isoformat()
        ))

        trade_id = cur.lastrowid
        await db.commit()

    return web.json_response({
        "ok": True,
        "trade_id": trade_id,
        "status": "pending",
        "message": "Сделка создана. Ожидается оплата."
    })


async def get_trades(request):
    user_id = int(request.query.get("user_id", 0))

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT
            id,listing_id,buyer_id,seller_id,
            amount,currency,status,tx_hash,created_at
        FROM trades
        WHERE buyer_id=? OR seller_id=?
        ORDER BY id DESC
        """, (user_id, user_id))

        rows = await cur.fetchall()

    result = []
    for r in rows:
        result.append({
            "id": r[0],
            "listing_id": r[1],
            "buyer_id": r[2],
            "seller_id": r[3],
            "amount": r[4],
            "currency": r[5],
            "status": r[6],
            "tx_hash": r[7] or "",
            "created_at": r[8]
        })

    return web.json_response({
        "ok": True,
        "trades": result
    })


async def update_trade_status(request):
    data = await json_body(request)

    trade_id = int(data.get("trade_id", 0))
    user_id = int(data.get("user_id", 0))
    new_status = str(data.get("status") or "")

    allowed = {
        "delivered",
        "completed",
        "cancelled"
    }

    if new_status not in allowed:
        return web.json_response(
            {
                "ok": False,
                "error": "Этот статус нельзя установить вручную"
            },
            status=400
        )

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT buyer_id,seller_id,status
        FROM trades
        WHERE id=?
        """, (trade_id,))
        row = await cur.fetchone()

        if not row:
            return web.json_response(
                {"ok": False, "error": "Сделка не найдена"},
                status=404
            )

        buyer_id, seller_id, status = row

        if new_status == "delivered":
            if user_id != seller_id or status != "paid":
                return web.json_response(
                    {"ok": False, "error": "Нельзя передать товар сейчас"},
                    status=403
                )

        elif new_status == "completed":
            if user_id != buyer_id or status != "delivered":
                return web.json_response(
                    {"ok": False, "error": "Нельзя завершить сделку сейчас"},
                    status=403
                )

        elif new_status == "cancelled":
            if user_id not in (buyer_id, seller_id):
                return web.json_response(
                    {"ok": False, "error": "Нет доступа"},
                    status=403
                )

        await db.execute("""
        UPDATE trades SET status=?
        WHERE id=?
        """, (new_status, trade_id))

        await db.commit()

    return web.json_response({"ok": True})


async def submit_tx(request):
    """
    Безопасный режим:
    транзакция записывается как заявка на проверку.
    Она НЕ считается подтверждённой оплатой автоматически.
    """
    data = await json_body(request)

    trade_id = int(data.get("trade_id", 0))
    user_id = int(data.get("user_id", 0))
    tx_hash = str(data.get("tx_hash") or "").strip()

    if not tx_hash:
        return web.json_response(
            {"ok": False, "error": "Укажи хэш транзакции"},
            status=400
        )

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT buyer_id,status FROM trades WHERE id=?
        """, (trade_id,))
        row = await cur.fetchone()

        if not row:
            return web.json_response(
                {"ok": False, "error": "Сделка не найдена"},
                status=404
            )

        buyer_id, status = row

        if buyer_id != user_id:
            return web.json_response(
                {"ok": False, "error": "Нет доступа"},
                status=403
            )

        if status != "pending":
            return web.json_response(
                {"ok": False, "error": "Эта сделка уже обработана"},
                status=400
            )

        await db.execute("""
        UPDATE trades SET tx_hash=?
        WHERE id=?
        """, (tx_hash, trade_id))

        await db.commit()

    return web.json_response({
        "ok": True,
        "status": "pending",
        "message": "Транзакция отправлена на проверку."
    })


async def get_reviews(request):
    seller_id = int(request.query.get("seller_id", 0))

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT r.id,r.buyer_id,r.rating,r.text,r.created_at,
               u.username,u.first_name
        FROM reviews r
        LEFT JOIN users u ON u.id=r.buyer_id
        WHERE r.seller_id=?
        ORDER BY r.id DESC
        LIMIT 50
        """, (seller_id,))
        rows = await cur.fetchall()

    reviews = []
    ratings = []

    for r in rows:
        ratings.append(r[2])
        reviews.append({
            "id": r[0],
            "buyer_id": r[1],
            "rating": r[2],
            "text": r[3] or "",
            "created_at": r[4],
            "username": r[5] or "",
            "first_name": r[6] or "Пользователь"
        })

    return web.json_response({
        "ok": True,
        "average": round(sum(ratings) / len(ratings), 1)
        if ratings else 0,
        "count": len(ratings),
        "reviews": reviews
    })


async def create_review(request):
    data = await json_body(request)

    seller_id = int(data.get("seller_id", 0))
    buyer_id = int(data.get("buyer_id", 0))
    rating = int(data.get("rating", 0))
    text = str(data.get("text") or "").strip()

    if seller_id == buyer_id:
        return web.json_response(
            {"ok": False, "error": "Нельзя оценить себя"},
            status=400
        )

    if rating < 1 or rating > 5:
        return web.json_response(
            {"ok": False, "error": "Оценка от 1 до 5"},
            status=400
        )

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT id FROM reviews
        WHERE seller_id=? AND buyer_id=?
        """, (seller_id, buyer_id))

        if await cur.fetchone():
            return web.json_response(
                {"ok": False, "error": "Ты уже оставлял отзыв"},
                status=400
            )

        await db.execute("""
        INSERT INTO reviews
        (seller_id,buyer_id,rating,text,created_at)
        VALUES(?,?,?,?,?)
        """, (
            seller_id,buyer_id,rating,text,
            datetime.utcnow().isoformat()
        ))
        await db.commit()

    return web.json_response({"ok": True})


async def chat_get(request):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT id,user_id,username,first_name,photo_url,text,created_at
        FROM public_chat
        ORDER BY id DESC
        LIMIT 100
        """)
        rows = await cur.fetchall()

    rows.reverse()

    return web.json_response({
        "ok": True,
        "messages": [
            {
                "id": r[0],
                "user_id": r[1],
                "username": r[2] or "",
                "first_name": r[3] or "Пользователь",
                "photo_url": r[4] or "",
                "text": r[5],
                "created_at": r[6]
            }
            for r in rows
        ]
    })


async def chat_post(request):
    data = await json_body(request)

    user_id = int(data.get("user_id", 0))
    username = str(data.get("username") or "")
    first_name = str(data.get("first_name") or "Пользователь")
    photo_url = str(data.get("photo_url") or "")
    text = str(data.get("text") or "").strip()

    if not user_id or not text:
        return web.json_response(
            {"ok": False, "error": "Пустое сообщение"},
            status=400
        )

    if len(text) > 500:
        return web.json_response(
            {"ok": False, "error": "Максимум 500 символов"},
            status=400
        )

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        INSERT INTO public_chat
        (user_id,username,first_name,photo_url,text,created_at)
        VALUES(?,?,?,?,?,?)
        """, (
            user_id,username,first_name,photo_url,text,
            datetime.utcnow().isoformat()
        ))
        message_id = cur.lastrowid
        await db.commit()

    return web.json_response({
        "ok": True,
        "id": message_id
    })


@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        return web.Response(
            status=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "86400",
            },
        )

    try:
        response = await handler(request)
    except web.HTTPException as e:
        response = e

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"

    return response


async def main():
    await init_db()

    app = web.Application(middlewares=[cors_middleware])

    app.router.add_get("/", index)

    app.router.add_get("/api/listings", listings)
    app.router.add_post("/api/listings", create_listing)
    app.router.add_patch("/api/listings/close", close_listing)

    app.router.add_get(
        "/api/payment-methods/{seller_id}",
        payment_methods
    )
    app.router.add_post(
        "/api/payment-methods",
        save_payment_methods
    )

    app.router.add_post("/api/trades", create_trade)
    app.router.add_get("/api/trades", get_trades)
    app.router.add_patch("/api/trades/status", update_trade_status)
    app.router.add_post("/api/trades/tx", submit_tx)

    app.router.add_get("/api/reviews", get_reviews)
    app.router.add_post("/api/reviews", create_review)

    app.router.add_get("/api/chat", chat_get)
    app.router.add_post("/api/chat", chat_post)

    app.router.add_static("/", WEB, show_index=True)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)

    print("===================================")
    print("🌊 ATLANTIDA MARKET")
    print("🌐 SERVER STARTED")
    print(f"PORT: {port}")
    print("===================================")

    await site.start()

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
