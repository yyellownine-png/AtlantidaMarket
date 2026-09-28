from aiohttp import web
from pathlib import Path

BASE = Path(__file__).parent
WEB = BASE / "web"

async def index(request):
    return web.FileResponse(WEB / "index.html")

app = web.Application()
app.router.add_get("/", index)
app.router.add_static("/", WEB, show_index=True)

print("===================================")
print("🌊 ATLANTIDA MARKET WEB")
print("🌐 http://127.0.0.1:8080")
print("===================================")

web.run_app(app, host="0.0.0.0", port=8080)
