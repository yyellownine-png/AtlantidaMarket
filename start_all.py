import asyncio
import subprocess
import sys

async def main():
    api = subprocess.Popen([sys.executable, "run_market.py"])

    try:
        bot = subprocess.Popen([sys.executable, "bot.py"])
        await asyncio.to_thread(bot.wait)
    finally:
        api.terminate()
        try:
            api.wait(timeout=5)
        except subprocess.TimeoutExpired:
            api.kill()

if __name__ == "__main__":
    asyncio.run(main())
