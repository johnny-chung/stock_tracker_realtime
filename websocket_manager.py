from typing import Dict, Set
import json


class ConnectionManager:
    """Manage websocket connections and topic subscriptions.

    Topics are simple strings like 'all' or 'symbol:AAPL'.
    """

    def __init__(self):
        self.active_connections: Set = set()
        self.topic_subscriptions: Dict[str, Set] = {}
        self.ws_topics: Dict = {}
        # Redis config (optional) - populated by main on startup
        self._redis_url: str | None = None
        self._redis_channel: str | None = None

    async def connect(self, websocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        self.ws_topics[websocket] = set()
        # default subscription
        self.subscribe(websocket, "all")

    def subscribe(self, websocket, topic: str):
        # add mapping websocket -> topic and topic -> websocket
        self.ws_topics.setdefault(websocket, set()).add(topic)
        self.topic_subscriptions.setdefault(topic, set()).add(websocket)

    def unsubscribe(self, websocket, topic: str):
        if websocket in self.ws_topics:
            self.ws_topics[websocket].discard(topic)
        if topic in self.topic_subscriptions:
            self.topic_subscriptions[topic].discard(websocket)

    async def disconnect(self, websocket):
        # remove from all topics
        topics = self.ws_topics.pop(websocket, set())
        for t in topics:
            self.topic_subscriptions.get(t, set()).discard(websocket)
        self.active_connections.discard(websocket)

    async def send_personal_message(self, websocket, message: Dict):
        try:
            await websocket.send_text(json.dumps(message))
        except Exception:
            await self.disconnect(websocket)

    async def broadcast(self, message: Dict, topic: str = "all"):
        conns = set(self.topic_subscriptions.get(topic, set()))
        for ws in conns:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                await self.disconnect(ws)
