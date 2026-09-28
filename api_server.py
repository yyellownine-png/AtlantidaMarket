import asyncio
import os
import aiosqlite
from aiohttp import web
from pathlib import Path

BASE = Path(__file__).parent
WEB = BASE / "web"
DB = BASE / "atlantida.db"

async def get_listings(request):
    category = request.query.get("category", "")
    search = request.query.get("search", "")

    async with aiosqlite.connect(DB) as db:
        if category:
            cur = await db.execute("""
                SELECT id,seller_id,category,name,amount,price,description
                FROM listings
                WHERE status='active' AND category=?
                ORDER BY id DESC
            """, (category,))
        elif search:
            q = f"%{search}%"
            cur = await db.execute("""
                SELECT id,seller_id,category,name,amount,price,description
                FROM listings
                WHERE status='active'
                AND (name LIKE ? OR description LIKE ?)
                ORDER BY id DESC
            """, (q,q))
        else:
            cur = await db.execute("""
                SELECT id,seller_id,category,name,amount,price,description
                FROM listings
                WHERE status='active'
                ORDER BY id DESC
                LIMIT 100
            """)

        rows = await cur.fetchall()

    return web.json_response([
        {
            "id": r[0],
            "seller_id": r[1],
            "category": r[2],
            "name": r[3],
            "amount": r[4],
            "price": r[5],
            "description": r[6] or ""
        }
        for r in rows
    ])


async def create_listing(request):
    data = await request.json()

    required = ["seller_id","category","name","amount","price"]

    if not all(x in data for x in required):
        return web.json_response(
            {"ok": False, "error": "missing_fields"},
            status=400
        )

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
            INSERT INTO listings
            (seller_id,category,name,amount,price,description,status,created_at)
            VALUES (?,?,?,?,?,?,?,datetime('now'))
        """, (
            int(data["seller_id"]),
            data["category"],
            data["name"],
            data["amount"],
            data["price"],
            data.get("description",""),
            "active"
        ))

        listing_id = cur.lastrowid
        await db.commit()

    return web.json_response({
        "ok": True,
        "id": listing_id
    })


async def create_trade(request):
    data = await request.json()

    listing_id = int(data["listing_id"])
    buyer_id = int(data["buyer_id"])

    async with aiosqlite.connect(DB) as db:

        cur = await db.execute("""
            SELECT seller_id,status
            FROM listings
            WHERE id=?
        """, (listing_id,))

        row = await cur.fetchone()

        if not row:
            return web.json_response(
                {"ok":False,"error":"listing_not_found"},
                status=404
            )

        seller_id,status = row

        if status != "active":
            return web.json_response(
                {"ok":False,"error":"listing_closed"},
                status=400
            )

        if seller_id == buyer_id:
            return web.json_response(
                {"ok":False,"error":"own_listing"},
                status=400
            )

        cur = await db.execute("""
            INSERT INTO trades
            (listing_id,buyer_id,seller_id,status,created_at)
            VALUES (?,?,?,?,datetime('now'))
        """, (
            listing_id,
            buyer_id,
            seller_id,
            "created"
        ))

        trade_id = cur.lastrowid
        await db.commit()

    return web.json_response({
        "ok":True,
        "trade_id":trade_id
    })


async def index(request):
    return web.FileResponse(WEB / "index.html")


async def main():
    app = web.Application()

    app.router.add_get("/", index)
    app.router.add_get("/api/listings", get_listings)
    app.router.add_post("/api/listings", create_listing)
    app.router.add_post("/api/trades", create_trade)

    app.router.add_static(
        "/",
        WEB,
        show_index=True
    )

    print("===================================")
    print("🌊 ATLANTIDA MARKET API")
    print("🌐 http://127.0.0.1:8080")
    print("===================================")

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        8080
    )

    await site.start()

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
