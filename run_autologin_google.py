
import asyncio
from app.bridge_ws.autologin import auto_login_google

if __name__ == "__main__":
    asyncio.run(auto_login_google())
