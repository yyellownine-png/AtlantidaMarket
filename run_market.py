import asyncio
import os
import subprocess
import re
import urllib.request
import urllib.parse
import json

from dotenv import load_dotenv
from aiohttp import web

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN or TOKEN == "ТОКЕН_ТВОЕГО_БОТА":
    raise RuntimeError("BOT_TOKEN не найден в .env")

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")


DB = os.path.join(BASE, "atlantida.db")


async def init_db():
    import aiosqlite

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seller_payment_methods (
                seller_id INTEGER PRIMARY KEY,
                crypto_send TEXT,
                ton_wallet TEXT,
                usdt_wallet TEXT,
                card_info TEXT,
                updated_at TEXT
            )
        """)

        # Миграция старой БД: добавляем USDT ERC-20, если колонки ещё нет
        async with db.execute(
            "PRAGMA table_info(seller_payment_methods)"
        ) as cur:
            columns = [row[1] for row in await cur.fetchall()]

        if "usdt_wallet" not in columns:
            await db.execute(
                "ALTER TABLE seller_payment_methods ADD COLUMN usdt_wallet TEXT"
            )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                amount TEXT NOT NULL,
                price TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL,
                buyer_id INTEGER NOT NULL,
                seller_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                created_at TEXT NOT NULL
            )
        """)

        await db.commit()


async def index(request):
    return web.FileResponse(
        os.path.join(WEB, "index.html")
    )


async def listings(request):
    import aiosqlite

    db_path = os.path.join(BASE, "atlantida.db")

    category = request.query.get("category")
    search = request.query.get("search")

    async with aiosqlite.connect(db_path) as db:

        if category:
            cur = await db.execute("""
                SELECT id,seller_id,category,name,amount,price,description
                FROM listings
                WHERE status='active' AND category=?
                ORDER BY id DESC
            """,(category,))

        elif search:
            q="%"+search+"%"
            cur=await db.execute("""
                SELECT id,seller_id,category,name,amount,price,description
                FROM listings
                WHERE status='active'
                AND (name LIKE ? OR description LIKE ?)
                ORDER BY id DESC
            """,(q,q))

        else:
            cur=await db.execute("""
                SELECT id,seller_id,category,name,amount,price,description
                FROM listings
                WHERE status='active'
                ORDER BY id DESC
                LIMIT 100
            """)

        rows=await cur.fetchall()

    return web.json_response([
        {
            "id":r[0],
            "seller_id":r[1],
            "category":r[2],
            "name":r[3],
            "amount":r[4],
            "price":r[5],
            "description":r[6] or ""
        }
        for r in rows
    ])


async def create_listing(request):
    import aiosqlite
    from datetime import datetime

    data=await request.json()

    db_path=os.path.join(BASE,"atlantida.db")

    async with aiosqlite.connect(db_path) as db:

        cur=await db.execute("""
            INSERT INTO listings
            (seller_id,category,name,amount,price,description,status,created_at)
            VALUES(?,?,?,?,?,?,?,?)
        """,(
            int(data["seller_id"]),
            data["category"],
            data["name"],
            data["amount"],
            data["price"],
            data.get("description",""),
            "active",
            datetime.now().isoformat()
        ))

        listing_id=cur.lastrowid

        await db.commit()

    return web.json_response({
        "ok":True,
        "id":listing_id
    })



async def telegram_notify(chat_id, message):
    if not TOKEN or not chat_id:
        return False

    import aiohttp

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json={
                "chat_id": int(chat_id),
                "text": message
            },
            timeout=10
        ) as response:
            return response.status == 200


async def create_trade(request):
    import aiosqlite
    from datetime import datetime

    try:
        data = await request.json()

        listing_id = int(data["listing_id"])
        buyer_id = int(data["buyer_id"])
        amount = str(data.get("amount", ""))
        currency = str(data.get("currency", "")).upper()

        if currency not in ("TON", "USDT"):
            return web.json_response(
                {"ok": False, "error": "unsupported_currency"},
                status=400
            )

        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("""
                SELECT seller_id, price, name, status
                FROM listings
                WHERE id=?
            """, (listing_id,))
            row = await cur.fetchone()

            if not row:
                return web.json_response(
                    {"ok": False, "error": "listing_not_found"},
                    status=404
                )

            seller_id, listing_price, listing_name, listing_status = row

            if listing_status != "active":
                return web.json_response(
                    {"ok": False, "error": "listing_closed"},
                    status=400
                )

            if seller_id == buyer_id:
                return web.json_response(
                    {"ok": False, "error": "own_listing"},
                    status=400
                )

            # Если цена пришла с клиента — используем цену самого объявления.
            if not amount:
                amount = str(listing_price)

            cur = await db.execute("""
                INSERT INTO trades
                (listing_id, buyer_id, seller_id, amount, currency, status, created_at)
                VALUES(?,?,?,?,?,?,?)
            """, (
                listing_id,
                buyer_id,
                seller_id,
                amount,
                currency,
                "pending",
                datetime.now().isoformat()
            ))

            trade_id = cur.lastrowid
            await db.commit()

        # Уведомление продавцу
        try:
            await telegram_notify(
                seller_id,
                f"🛒 Новая сделка #{trade_id}\n\n"
                f"Товар: {listing_name}\n"
                f"Сумма: {amount} {currency}\n"
                f"Статус: ⏳ Ожидает оплаты"
            )
        except Exception:
            pass

        return web.json_response({
            "ok": True,
            "trade_id": trade_id,
            "status": "pending"
        })

    except Exception as e:
        return web.json_response(
            {"ok": False, "error": str(e)},
            status=500
        )


async def save_payment_method(request):
    import aiosqlite

    try:
        data = await request.json()
        seller_id = int(data.get("seller_id", 0))
        ton_wallet = str(data.get("ton_wallet", "")).strip()
        usdt_wallet = str(data.get("usdt_wallet", "")).strip()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_data"}, status=400)

    if not seller_id:
        return web.json_response(
            {"ok": False, "error": "invalid_seller_id"},
            status=400
        )

    if not ton_wallet and not usdt_wallet:
        return web.json_response(
            {"ok": False, "error": "no_wallet"},
            status=400
        )

    if ton_wallet and not (
        ton_wallet.startswith("EQ") or
        ton_wallet.startswith("UQ") or
        ton_wallet.startswith("kQ")
    ):
        return web.json_response(
            {"ok": False, "error": "invalid_ton_wallet"},
            status=400
        )

    if usdt_wallet and not re.fullmatch(r"0x[a-fA-F0-9]{40}", usdt_wallet):
        return web.json_response(
            {"ok": False, "error": "invalid_usdt_erc20_wallet"},
            status=400
        )

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seller_payment_methods (
                seller_id INTEGER PRIMARY KEY,
                crypto_send TEXT,
                ton_wallet TEXT,
                usdt_wallet TEXT,
                card_info TEXT,
                updated_at TEXT
            )
        """)

        await db.execute("""
            INSERT INTO seller_payment_methods
                (seller_id, ton_wallet, usdt_wallet, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(seller_id) DO UPDATE SET
                ton_wallet=excluded.ton_wallet,
                usdt_wallet=excluded.usdt_wallet,
                updated_at=excluded.updated_at
        """, (seller_id, ton_wallet, usdt_wallet))

        await db.commit()

    return web.json_response({
        "ok": True,
        "seller_id": seller_id,
        "ton_wallet": ton_wallet,
        "usdt_wallet": usdt_wallet
    })


async def get_payment_method(request):
    import aiosqlite

    try:
        seller_id = int(request.match_info["seller_id"])
    except Exception:
        return web.json_response(
            {"ok": False, "error": "invalid_seller_id"},
            status=400
        )

    try:
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute(
                "PRAGMA table_info(seller_payment_methods)"
            )
            columns = [row[1] for row in await cur.fetchall()]

            if "usdt_wallet" not in columns:
                await db.execute(
                    "ALTER TABLE seller_payment_methods ADD COLUMN usdt_wallet TEXT"
                )
                await db.commit()

            cur = await db.execute("""
                SELECT seller_id, ton_wallet, usdt_wallet
                FROM seller_payment_methods
                WHERE seller_id=?
            """, (seller_id,))

            row = await cur.fetchone()

        if not row:
            return web.json_response({
                "ok": True,
                "connected": False,
                "ton_wallet": "",
                "usdt_wallet": ""
            })

        return web.json_response({
            "ok": True,
            "connected": bool(row[1] or row[2]),
            "seller_id": row[0],
            "ton_wallet": row[1] or "",
            "usdt_wallet": row[2] or ""
        })

    except Exception as e:
        return web.json_response({
            "ok": False,
            "error": type(e).__name__,
            "message": str(e)
        }, status=500)


async def delete_payment_method(request):
    import aiosqlite

    try:
        data = await request.json()
        seller_id = int(data.get("seller_id", 0))
    except Exception:
        return web.json_response(
            {"ok": False, "error": "invalid_data"},
            status=400
        )

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            DELETE FROM seller_payment_methods
            WHERE seller_id=?
        """, (seller_id,))
        await db.commit()

    return web.json_response({"ok": True})



async def get_public_chat(request):
    import aiosqlite

    try:
        user_id = int(request.query.get("user_id", 0))
    except Exception:
        return web.json_response(
            {"ok": False, "error": "invalid_user_id"},
            status=400
        )

    if not user_id:
        return web.json_response(
            {"ok": False, "error": "invalid_user_id"},
            status=400
        )

    async with aiosqlite.connect(DB) as db:

        await db.execute("""
            CREATE TABLE IF NOT EXISTS public_chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                photo_url TEXT DEFAULT '',
                text TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            await db.execute("ALTER TABLE public_chat ADD COLUMN photo_url TEXT DEFAULT ''")
            await db.commit()
        except Exception:
            pass

        cur = await db.execute("""
            SELECT
                id,
                user_id,
                username,
                first_name,
                photo_url,
                text,
                created_at
            FROM public_chat
            ORDER BY id DESC
            LIMIT 100
        """)

        rows = await cur.fetchall()

    messages = []

    for r in reversed(rows):
        messages.append({
            "id": r[0],
            "user_id": r[1],
            "username": r[2] or "",
            "first_name": r[3] or "Игрок",
            "photo_url": r[4] or "",
            "text": r[5],
            "created_at": r[6]
        })

    return web.json_response({
        "ok": True,
        "messages": messages
    })


async def send_public_chat(request):
    import aiosqlite
    from datetime import datetime

    try:
        data = await request.json()

        user_id = int(data.get("user_id", 0))
        username = str(data.get("username", ""))[:64]
        first_name = str(
            data.get("first_name", "Игрок")
        )[:64]

        photo_url = str(
            data.get("photo_url", "")
        )[:1000]

        text = str(
            data.get("text", "")
        ).strip()

    except Exception:
        return web.json_response(
            {"ok": False, "error": "invalid_data"},
            status=400
        )

    if not user_id or not text:
        return web.json_response(
            {"ok": False, "error": "invalid_data"},
            status=400
        )

    if len(text) > 500:
        return web.json_response(
            {"ok": False, "error": "message_too_long"},
            status=400
        )

    async with aiosqlite.connect(DB) as db:

        await db.execute("""
            CREATE TABLE IF NOT EXISTS public_chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                photo_url TEXT DEFAULT '',
                text TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            await db.execute("ALTER TABLE public_chat ADD COLUMN photo_url TEXT DEFAULT ''")
            await db.commit()
        except Exception:
            pass

        now = datetime.now().isoformat(timespec="seconds")

        cur = await db.execute("""
            INSERT INTO public_chat
            (
                user_id,
                username,
                first_name,
                photo_url,
                text,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            username,
            first_name,
            photo_url,
            text,
            now
        ))

        message_id = cur.lastrowid

        await db.commit()

    return web.json_response({
        "ok": True,
        "message": {
            "id": message_id,
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "photo_url": photo_url,
            "text": text,
            "created_at": now
        }
    })



async def get_reviews(request):
    import aiosqlite

    try:
        seller_id = int(request.query.get("seller_id", 0))
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_seller_id"}, status=400)

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seller_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER NOT NULL,
                buyer_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                text TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

        cur = await db.execute("""
            SELECT id, buyer_id, rating, text, created_at
            FROM seller_reviews
            WHERE seller_id=?
            ORDER BY id DESC
        """, (seller_id,))

        rows = await cur.fetchall()

    reviews = [
        {
            "id": r[0],
            "buyer_id": r[1],
            "rating": r[2],
            "text": r[3] or "",
            "created_at": r[4]
        }
        for r in rows
    ]

    average = round(
        sum(x["rating"] for x in reviews) / len(reviews), 1
    ) if reviews else 0

    return web.json_response({
        "ok": True,
        "seller_id": seller_id,
        "average": average,
        "count": len(reviews),
        "reviews": reviews
    })


async def create_review(request):
    import aiosqlite

    try:
        data = await request.json()
        seller_id = int(data.get("seller_id", 0))
        buyer_id = int(data.get("buyer_id", 0))
        rating = int(data.get("rating", 0))
        text = str(data.get("text", "")).strip()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_data"}, status=400)

    if not seller_id or not buyer_id:
        return web.json_response({"ok": False, "error": "invalid_user"}, status=400)

    if seller_id == buyer_id:
        return web.json_response({"ok": False, "error": "self_review"}, status=400)

    if rating < 1 or rating > 5:
        return web.json_response({"ok": False, "error": "invalid_rating"}, status=400)

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seller_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER NOT NULL,
                buyer_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                text TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur = await db.execute("""
            SELECT id FROM seller_reviews
            WHERE seller_id=? AND buyer_id=?
        """, (seller_id, buyer_id))

        if await cur.fetchone():
            return web.json_response({
                "ok": False,
                "error": "already_reviewed"
            }, status=409)

        await db.execute("""
            INSERT INTO seller_reviews
                (seller_id, buyer_id, rating, text)
            VALUES (?, ?, ?, ?)
        """, (seller_id, buyer_id, rating, text))

        await db.commit()

    return web.json_response({
        "ok": True,
        "seller_id": seller_id,
        "rating": rating
    })



async def get_trades(request):
    import aiosqlite

    try:
        user_id = int(request.query.get("user_id", 0))
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_user_id"}, status=400)

    if not user_id:
        return web.json_response({"ok": False, "error": "invalid_user_id"}, status=400)

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER,
                buyer_id INTEGER,
                seller_id INTEGER,
                amount TEXT,
                currency TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

        cur = await db.execute("""
            SELECT id, listing_id, buyer_id, seller_id,
                   amount, currency, status, created_at
            FROM trades
            WHERE buyer_id=? OR seller_id=?
            ORDER BY id DESC
        """, (user_id, user_id))

        rows = await cur.fetchall()

    return web.json_response({
        "ok": True,
        "trades": [
            {
                "id": r[0],
                "listing_id": r[1],
                "buyer_id": r[2],
                "seller_id": r[3],
                "amount": r[4],
                "currency": r[5],
                "status": r[6],
                "created_at": r[7]
            }
            for r in rows
        ]
    })


async def update_trade_status(request):
    import aiosqlite

    try:
        data = await request.json()

        trade_id = int(data.get("trade_id", 0))
        user_id = int(data.get("user_id", 0))
        new_status = str(data.get("status", "")).strip()

        allowed = {
            "pending",
            "paid",
            "delivered",
            "completed",
            "cancelled"
        }

        if not trade_id or not user_id or new_status not in allowed:
            return web.json_response(
                {"ok": False, "error": "invalid_trade"},
                status=400
            )

        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("""
                SELECT buyer_id, seller_id, amount, currency
                FROM trades
                WHERE id=?
            """, (trade_id,))
            row = await cur.fetchone()

            if not row:
                return web.json_response(
                    {"ok": False, "error": "trade_not_found"},
                    status=404
                )

            buyer_id, seller_id, amount, currency = row

            # Кто имеет право менять конкретный статус
            if new_status == "paid" and user_id != buyer_id:
                return web.json_response(
                    {"ok": False, "error": "buyer_only"},
                    status=403
                )

            if new_status == "delivered" and user_id != seller_id:
                return web.json_response(
                    {"ok": False, "error": "seller_only"},
                    status=403
                )

            if new_status == "completed" and user_id != buyer_id:
                return web.json_response(
                    {"ok": False, "error": "buyer_only"},
                    status=403
                )

            if new_status == "cancelled" and user_id not in (buyer_id, seller_id):
                return web.json_response(
                    {"ok": False, "error": "access_denied"},
                    status=403
                )

            await db.execute("""
                UPDATE trades
                SET status=?
                WHERE id=?
            """, (new_status, trade_id))

            await db.commit()

        messages = {
            "paid":
                f"💳 Покупатель отметил оплату по сделке #{trade_id}.\n"
                f"Сумма: {amount} {currency}\n\n"
                f"Проверь поступление средств и передай товар.",

            "delivered":
                f"📦 Продавец передал товар по сделке #{trade_id}.\n\n"
                f"Проверь получение и подтверди сделку.",

            "completed":
                f"✅ Сделка #{trade_id} завершена.\n\n"
                f"Спасибо за использование Atlantida Market.",

            "cancelled":
                f"❌ Сделка #{trade_id} отменена."
        }

        # Уведомляем вторую сторону
        if new_status == "paid":
            await telegram_notify(seller_id, messages["paid"])

        elif new_status == "delivered":
            await telegram_notify(buyer_id, messages["delivered"])

        elif new_status == "completed":
            await telegram_notify(seller_id, messages["completed"])

        elif new_status == "cancelled":
            other_id = seller_id if user_id == buyer_id else buyer_id
            await telegram_notify(other_id, messages["cancelled"])

        return web.json_response({
            "ok": True,
            "trade_id": trade_id,
            "status": new_status
        })

    except Exception as e:
        return web.json_response(
            {"ok": False, "error": str(e)},
            status=500
        )


async def start_server():
    app = web.Application()

    app.router.add_get("/", index)
    app.router.add_get("/api/listings", listings)
    app.router.add_post("/api/listings", create_listing)

    app.router.add_post("/api/trades", create_trade)

    app.router.add_get("/api/chat", get_public_chat)
    app.router.add_post("/api/chat", send_public_chat)

    app.router.add_get("/api/reviews", get_reviews)
    app.router.add_post("/api/reviews", create_review)

    app.router.add_get("/api/trades", get_trades)
    app.router.add_patch("/api/trades/status", update_trade_status)

    app.router.add_post(
        "/api/payment-methods",
        save_payment_method
    )

    app.router.add_get(
        "/api/payment-methods/{seller_id}",
        get_payment_method
    )

    app.router.add_delete(
        "/api/payment-methods",
        delete_payment_method
    )

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        int(os.getenv("PORT", "8080"))
    )

    await site.start()

    print("Atlantida Market server started")

    while True:
        await asyncio.sleep(3600)


async def main():
    await init_db()
    await start_server()


if __name__=="__main__":
    asyncio.run(main())
