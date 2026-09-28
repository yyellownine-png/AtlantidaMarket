import asyncio
import os
import subprocess
import re
import urllib.request
import json

from dotenv import load_dotenv
from aiohttp import web

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN or TOKEN == "ТОКЕН_ТВОЕГО_БОТА":
    raise RuntimeError("BOT_TOKEN не найден в .env")

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")


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


async def start_server():

    app=web.Application()

    app.router.add_get("/",index)
    app.router.add_get("/api/listings",listings)
    app.router.add_post("/api/listings",create_listing)
    app.router.add_post("/api/trades",create_trade)

    app.router.add_static(
        "/",
        WEB
    )

    runner=web.AppRunner(app)
    await runner.setup()

    site=web.TCPSite(
        runner,
        "0.0.0.0",
        8080
    )

    await site.start()

    print("🌊 Market server: 8080")

    while True:
        await asyncio.sleep(3600)


async def main():

    await start_server()


if __name__=="__main__":
    asyncio.run(main())
