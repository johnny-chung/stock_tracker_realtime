import asyncio
import os
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Use simple absolute package imports. Prefer running as a module
# (python -m realtime_service.main) so package-relative imports inside
# submodules work without hacks.
from websocket_manager import ConnectionManager
from change_listener import start_change_listener
from config import settings

app = FastAPI(title="Realtime WebSocket Service")
manager = ConnectionManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    # validate settings
    # settings already imported at module scope
    if not settings.MONGO_URI:
        raise RuntimeError("MONGO_URI is not set. Please set it in env or live_tracker/.env")
    if not settings.MONGO_DB_NAME:
        raise RuntimeError("MONGO_DB_NAME is not set. Please set it in env or live_tracker/config.yaml")

    # if Redis is configured, start a redis subscriber that forwards messages to manager
    if settings.REDIS_URL:
        # attach redis config to manager so the change-listener thread can publish via sync Redis
        manager._redis_url = settings.REDIS_URL
        manager._redis_channel = settings.REDIS_CHANNEL

        async def redis_subscriber():
            try:
                import redis.asyncio as aioredis
                r = aioredis.from_url(settings.REDIS_URL)
                pubsub = r.pubsub()
                await pubsub.subscribe(settings.REDIS_CHANNEL)
                async for message in pubsub.listen():
                    # message is a dict, with 'type' and 'data'
                    if message is None:
                        continue
                    if message.get("type") != "message":
                        continue
                    data = message.get("data")
                    try:
                        import json
                        payload = json.loads(data)
                        # forward to local clients
                        await manager.broadcast(payload, topic="all")
                        symbol = payload.get("payload", {}).get("symbol") or payload.get("payload", {}).get("related_symbol")
                        if symbol:
                            await manager.broadcast(payload, topic=f"symbol:{symbol}")
                    except Exception:
                        # ignore malformed messages
                        pass
            except Exception:
                # If redis subscription fails, just continue without it
                pass

        app.state.redis_task = asyncio.create_task(redis_subscriber())

    # start change listener in background
    app.state.change_task = asyncio.create_task(start_change_listener(manager))


@app.on_event("shutdown")
async def shutdown_event():
    task = getattr(app.state, "change_task", None)
    if task:
        task.cancel()


@app.get("/health")
async def health():
    """Simple health endpoint for Kubernetes liveness/readiness probes.

    Optionally this can be extended to check Redis/Mongo connectivity.
    """
    return {"status": "ok"}


@app.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket, token: str = Query(None)):
    # token param is optional; add auth here if you want
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # clients can send subscribe/unsubscribe messages as JSON
            try:
                obj = json.loads(data)
                action = obj.get("action")
                if action == "subscribe":
                    topic = obj.get("topic")
                    if topic:
                        manager.subscribe(websocket, topic)
                        await manager.send_personal_message(websocket, {"subscribed": topic})
                elif action == "unsubscribe":
                    topic = obj.get("topic")
                    if topic:
                        manager.unsubscribe(websocket, topic)
                        await manager.send_personal_message(websocket, {"unsubscribed": topic})
            except ValueError:
                # ignore non-json messages
                pass
    except WebSocketDisconnect:
        await manager.disconnect(websocket)


@app.websocket("/ws/notifications/{symbol}")
async def websocket_notifications_symbol(websocket: WebSocket, symbol: str, token: str = Query(None)):
    await manager.connect(websocket)
    # subscribe to symbol-specific topic
    manager.subscribe(websocket, f"symbol:{symbol}")
    try:
        while True:
            await websocket.receive_text()  # keep connection open; ignore client messages
    except WebSocketDisconnect:
        await manager.disconnect(websocket)


if __name__ == "__main__":
    # run the app instance directly so we don't force-import the package name
    # disable auto-reload on Windows shells that may lack required tools
    reload_flag = False if os.name == "nt" else True
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, reload=reload_flag)
