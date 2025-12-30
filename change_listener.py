import asyncio
import json
import traceback
from pymongo import MongoClient

from config import settings


def _watch_loop(uri: str, db_name: str, manager, loop):
    """Blocking watch loop run in a thread. Uses synchronous PyMongo and
    schedules async broadcasts on the given asyncio loop.
    """
    try:
        client = MongoClient(uri)
        db = client[db_name]
        # create a sync redis client if REDIS_URL present (thread publisher)
        redis_sync = None
        try:
            from redis import Redis
            if manager and hasattr(manager, "_redis_url") and manager._redis_url:
                redis_sync = Redis.from_url(manager._redis_url)
        except Exception:
            redis_sync = None

        with db.watch(full_document="updateLookup") as stream:
            for change in stream:
                try:
                    ns = change.get("ns", {})
                    coll = ns.get("coll")
                    full = change.get("fullDocument")
                    if not full:
                        continue

                    notification = {
                        "source": "signal" if coll == "signal" else "event" if coll == "event" else coll,
                        "original_id": str(full.get("_id")),
                        "created_at": full.get("created_at"),
                        "payload": full,
                    }

                    # If Redis is configured, publish JSON to Redis channel for other instances.
                    if redis_sync:
                        try:
                            redis_sync.publish(manager._redis_channel or "realtime_notifications", json.dumps(notification, default=str))
                        except Exception:
                            # fallback to local broadcast if Redis publish fails
                            asyncio.run_coroutine_threadsafe(manager.broadcast(notification, topic="all"), loop)
                            symbol = full.get("symbol") or full.get("related_symbol")
                            if symbol:
                                asyncio.run_coroutine_threadsafe(manager.broadcast(notification, topic=f"symbol:{symbol}"), loop)
                    else:
                        # schedule broadcasts on the asyncio loop
                        asyncio.run_coroutine_threadsafe(manager.broadcast(notification, topic="all"), loop)
                        symbol = full.get("symbol") or full.get("related_symbol")
                        if symbol:
                            asyncio.run_coroutine_threadsafe(manager.broadcast(notification, topic=f"symbol:{symbol}"), loop)
                except Exception:
                    traceback.print_exc()
    except Exception:
        traceback.print_exc()


async def start_change_listener(manager):
    """Start a change-stream listener using sync PyMongo in a background thread.

    This avoids Motor and uses PyMongo; the blocking watch runs in a separate
    thread and posts events back into the FastAPI asyncio loop.
    """
    uri = settings.MONGO_URI
    db_name = settings.MONGO_DB_NAME
    loop = asyncio.get_running_loop()

    # Try to use an async PyMongo client if available. Several distributions
    # expose an asyncio-compatible module path; test common names. If none are
    # available, fall back to the thread-based blocking watch implementation
    # (which uses the stable synchronous PyMongo client).
    async_client_cls = None
    async_mod = None
    for candidate in ("pymongo.asyncio", "pymongo_asyncio", "pymongo_async"):
        try:
            async_mod = __import__(candidate, fromlist=["*"])
            async_client_cls = getattr(async_mod, "MongoClient", None)
            if async_client_cls:
                break
        except Exception:
            async_mod = None
            async_client_cls = None

    if async_client_cls:
        # Native async PyMongo is available — use it.
        try:
            # create async client and watch the DB with async iteration
            client = async_client_cls(uri)
            db = client[db_name]

            # prepare async redis publisher if configured
            aioredis = None
            if manager and getattr(manager, "_redis_url", None):
                try:
                    import redis.asyncio as aioredis_mod
                    aioredis = aioredis_mod.from_url(manager._redis_url)
                except Exception:
                    aioredis = None

            while True:
                try:
                    async with db.watch(full_document="updateLookup") as stream:
                        async for change in stream:
                            try:
                                ns = change.get("ns", {})
                                coll = ns.get("coll")
                                full = change.get("fullDocument")
                                if not full:
                                    continue

                                notification = {
                                    "source": "signal" if coll == "signal" else "event" if coll == "event" else coll,
                                    "original_id": str(full.get("_id")),
                                    "created_at": full.get("created_at"),
                                    "payload": full,
                                }

                                # If Redis is configured, publish via async Redis
                                if aioredis:
                                    try:
                                        import json
                                        await aioredis.publish(manager._redis_channel or "realtime_notifications", json.dumps(notification, default=str))
                                    except Exception:
                                        # fallback to local broadcast on publish failure
                                        await manager.broadcast(notification, topic="all")
                                        symbol = full.get("symbol") or full.get("related_symbol")
                                        if symbol:
                                            await manager.broadcast(notification, topic=f"symbol:{symbol}")
                                else:
                                    await manager.broadcast(notification, topic="all")
                                    symbol = full.get("symbol") or full.get("related_symbol")
                                    if symbol:
                                        await manager.broadcast(notification, topic=f"symbol:{symbol}")
                            except Exception:
                                traceback.print_exc()
                except Exception:
                    # retry loop on errors
                    traceback.print_exc()
                    await asyncio.sleep(2)
        except Exception:
            # If async client usage fails for any reason, fall back to thread-based watch
            traceback.print_exc()

    # Fallback: run the blocking watch in a thread (synchronous PyMongo)
    while True:
        try:
            await asyncio.to_thread(_watch_loop, uri, db_name, manager, loop)
        except Exception:
            print("change listener error, retrying in 2s")
            traceback.print_exc()
            await asyncio.sleep(2)
