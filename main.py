from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from bot.core import BotCore
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    global botCore
    botCore = BotCore()
    await botCore.init_async()
    yield


app = FastAPI(lifespan=lifespan)
botCore: BotCore | None = None


@app.post('/')
@app.post('/{path:path}')
async def receive_msg(request: Request, path: str = ''):
    try:
        event = await request.json()
    except Exception:
        return JSONResponse({"error": "Empty or invalid JSON"}, status_code=400)

    if not event:
        return JSONResponse({"error": "Empty or invalid JSON"}, status_code=400)

    print(event)

    try:
        await botCore.handle(event)
        return JSONResponse({"status": "ok"}, status_code=200)
    except Exception as e:
        import traceback
        print(f"!!! 发生错误 !!!\n{traceback.format_exc()}")
        return JSONResponse({"status": "error"}, status_code=500)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8080)
