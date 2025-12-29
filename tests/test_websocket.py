"""Simple pytest for the realtime_service websocket endpoints.

This test connects to the `/ws/notifications` websocket, sends a
subscribe message and asserts the server replies with a confirmation
JSON message. It stubs out the long-running change listener started on
startup (which opens a MongoDB change stream) so the test can run in a
normal single-node/dev Mongo environment.
"""
import os
import asyncio
import importlib

# Ensure required env vars are present before importing the app
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "testdb")

from fastapi.testclient import TestClient


def _make_dummy_change_listener():
    async def _dummy(manager):
        # keep running until cancelled so the startup creates a task but it
        # doesn't try to open a change stream against a real replica-set.
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            return

    return _dummy


def test_subscribe_confirms():
    """Connect, send a subscribe action and expect a confirmation message."""
    # import the module so we can stub the change listener before startup
    main_mod = importlib.import_module("realtime_service.main")

    # replace the real change listener with a harmless coroutine so the
    # app.startup doesn't attempt to open a replica-set change stream.
    main_mod.start_change_listener = _make_dummy_change_listener()

    app = main_mod.app

    with TestClient(app) as client:
        with client.websocket_connect("/ws/notifications") as ws:
            ws.send_json({"action": "subscribe", "topic": "symbol:TEST"})
            # WebSocketTestSession.receive_json doesn't accept a `timeout`
            # kwarg in this environment; call the method directly.
            msg = ws.receive_json()
            assert msg == {"subscribed": "symbol:TEST"}
