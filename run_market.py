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


async def create_trade(request):
    import aiosqlite
    from datetime import datetime

    data=await request.json()

    listing_id=int(data["listing_id"])
    buyer_id=int(data["buyer_id"])

    db_path=os.path.join(BASE,"atlantida.db")

    async with aiosqlite.connect(db_path) as db:

        cur=await db.execute("""
            SELECT seller_id,status
            FROM listings
            WHERE id=?
        """,(listing_id,))

        row=await cur.fetchone()

        if not row:
            return web.json_response(
                {"ok":False,"error":"listing_not_found"},
                status=404
            )

        seller_id,status=row

        if status!="active":
            return web.json_response(
                {"ok":False,"error":"listing_closed"},
                status=400
            )

        if seller_id==buyer_id:
            return web.json_response(
                {"ok":False,"error":"own_listing"},
                status=400
            )

        cur=await db.execute("""
            INSERT INTO trades
            (listing_id,buyer_id,seller_id,status,created_at)
            VALUES(?,?,?,?,?)
        """,(
            listing_id,
            buyer_id,
            seller_id,
            "created",
            datetime.now().isoformat()
        ))

        trade_id=cur.lastrowid

        await db.commit()

    return web.json_response({
        "ok":True,
        "trade_id":trade_id
    })


def set_menu_button(url):

    api=(
        f"https://api.telegram.org/bot{TOKEN}/setChatMenuButton"
    )

    payload={
        "menu_button":json.dumps({
            "type":"web_app",
            "text":"🌊 Market",
            "web_app":{
                "url":url
            }
        })
    }

    req=urllib.request.Request(
        api,
        data=urllib.parse.urlencode(payload).encode(),
        headers={
            "Content-Type":
            "application/x-www-form-urlencoded"
        }
    )

    try:
        print(
            urllib.request.urlopen(req).read().decode()
        )
    except Exception as e:
        print("Menu button error:",e)



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


async def start_server():

    app = web.Application()

    app.router.add_get("/", index)
    app.router.add_get("/api/listings", listings)
    app.router.add_post("/api/listings", create_listing)
    app.router.add_post("/api/trades", create_trade)

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

    app.router.add_static("/", WEB)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        int(os.getenv("PORT", "8080"))
    )

    await site.start()

    print("🌊 Market server started")

    while True:
        await asyncio.sleep(3600)


async def main():
    await init_db()
    await start_server()


if __name__=="__main__":
    asyncio.run(main())
