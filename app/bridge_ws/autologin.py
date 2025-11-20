
import asyncio
from .integ import BridgeServer

async def auto_login_google(start_url="https://2nd-no.com/auth/login"):
    server = BridgeServer()
    await asyncio.sleep(0.8)                 # wait extension connection
    await server.send({"type":"open_tab", "url": start_url})
    # no explicit click needed; content scripts will auto-click
    await asyncio.sleep(2.0)
    return True
