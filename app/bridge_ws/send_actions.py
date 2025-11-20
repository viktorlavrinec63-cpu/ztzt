import asyncio
from .integ import BridgeServer

async def create_number_flow():
    s = BridgeServer()
    await asyncio.sleep(0.8)  # wait extension connection
    # optional: wait for loggedIn event on the server side if вы это обрабатываете
    steps = [
        {"type":"goto", "url":"https://2nd-no.com/app/numbers", "delay": 1200},
        {"type":"waitAndClickText", "texts":["Add new number","Добавить номер","Add number"], "timeout":20000},
        {"type":"waitAndClickText", "texts":["Next","Далее","Continue"], "timeout":20000},
        {"type":"waitAndClickText", "texts":["Create","Создать","Confirm","Подтвердить"], "timeout":20000},
    ]
    await s.send({"type":"runActions", "steps": steps})
    await asyncio.sleep(1.0)

if __name__ == "__main__":
    asyncio.run(create_number_flow())
