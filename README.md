# Realtime WebSocket Service

This FastAPI service watches MongoDB change streams and pushes notifications to connected WebSocket clients.

## Overview

- Purpose: Deliver near-real-time notifications for updates to the `signals` and `events` collections in your MongoDB database.
- Pattern: a blocking PyMongo change-stream watch runs in a background thread and schedules async broadcasts into FastAPI's event loop; a ConnectionManager forwards those messages to subscribed WebSocket clients.
- Database: By default the service reads the full connection string from `live_tracker/.env` (MONGO_URI) and the DB name from `live_tracker/config.yaml` (mongo.db). You can override with `realtime_service/.env` or environment variables.

## Key files

- `config.py` — loads config from env/.env and attempts to read `live_tracker/config.yaml` to pick up the DB name. Exposes `settings.MONGO_URI`, `settings.MONGO_DB_NAME`, `settings.HOST`, `settings.PORT`.
- `main.py` — FastAPI entrypoint. Creates the `ConnectionManager`, registers WebSocket endpoints, validates config on startup, and starts the change listener background task.
- `websocket_manager.py` — `ConnectionManager` implementation that tracks active WebSocket connections and topic subscriptions and provides `broadcast()` and `send_personal_message()`.
- `change_listener.py` — uses synchronous PyMongo `watch()` in a background thread and posts events back to the asyncio loop using `asyncio.run_coroutine_threadsafe()`.

## Runtime flow (Mongo -> Mobile client)

1. FastAPI starts and validates `MONGO_URI` and `MONGO_DB_NAME`.
2. `start_change_listener(manager)` is launched as a background task.
3. The change-listener runs a blocking `db.watch(full_document="updateLookup")` in a thread. For each change it:
   - determines the collection (`signals` or `events`), extracts `fullDocument`, and builds a notification object:
     ```json
     {"source":"signal","original_id":"<id>","created_at":...,"payload":{...}}
     ```
   - schedules `manager.broadcast(notification, topic="all")` on the FastAPI loop.
   - if the document contains a symbol (e.g. `symbol` or `related_symbol`), also schedules a broadcast to `topic = "symbol:<SYMBOL>"`.
4. Connected WebSocket clients receive the JSON text messages for topics they subscribed to.

## WebSocket endpoints and subscription model

- `GET /ws/notifications` (WebSocket upgrade) — default subscription to `all`. Client may send JSON messages to subscribe/unsubscribe:
  - `{ "action": "subscribe", "topic": "symbol:TD.TO" }`
  - `{ "action": "unsubscribe", "topic": "symbol:TD.TO" }`
- `GET /ws/notifications/{symbol}` — shorthand: connects and auto-subscribes to `symbol:{symbol}`.

## Message format (server -> client)

Server sends JSON-encoded messages. Example:

```json
{
  "source": "signal",
  "original_id": "650c9f9a12e4...",
  "created_at": "2025-12-26T16:28:00Z",
  "payload": {
    /* full Mongo document */
  }
}
```

## Configuration & credentials

- `MONGO_URI`: Full connection string (e.g. Atlas `mongodb+srv://...`). Put this in `live_tracker/.env` (already present) or create `realtime_service/.env`. The service will load `live_tracker/.env` automatically.
- `MONGO_DB_NAME`: Optional env var. If not provided the service reads `live_tracker/config.yaml` and uses `mongo.db` (e.g. `td_stock_tracker`).
- `HOST` / `PORT`: TCP address where FastAPI listens (default host `0.0.0.0`, port `8001`). `PORT` is the port your mobile app connects to (e.g. `ws://host:8001/ws/notifications`).

## Why a port is needed

- The Mongo Atlas connection string contains the DB host(s) and port(s) which are resolved via DNS SRV — you do not provide a port for Mongo when using `mongodb+srv://`.
- The `PORT` value in `realtime_service` is the TCP port for the WebSocket server (where clients connect). Ensure this port is accessible to clients (firewall, proxy, or container port mapping).

## How to run locally

1. Create and activate a virtualenv inside the realtime_service folder:

```bash
cd c:/Users/johnn/Desktop/Project/stock_tracker/realtime_service
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

2. Ensure `MONGO_URI` and `MONGO_DB_NAME` are available (service will load `live_tracker/.env` automatically). Example:

```bash
export MONGO_URI="mongodb+srv://<user>:<password>@cluster..."
export MONGO_DB_NAME=td_stock_tracker   # optional
```

3. Start the FastAPI server:

```bash
uvicorn realtime_service.main:app --reload --port 8001
```

4. Connect a client (examples below) and insert documents into the `signals` or `events` collections to see notifications.

## Quick test clients

- websocat (CLI):

```bash
websocat ws://localhost:8001/ws/notifications
```

- Python test client (async):

```py
import asyncio, websockets, json

async def main():
		uri = "ws://localhost:8001/ws/notifications"
		async with websockets.connect(uri) as ws:
				await ws.send(json.dumps({"action":"subscribe","topic":"symbol:TD.TO"}))
				while True:
						msg = await ws.recv()
						print(msg)

asyncio.run(main())
```

## Prerequisites & troubleshooting

- Change streams require MongoDB to be a replica set. For local testing, run a single-node replica set:
  ```bash
  mongod --dbpath /data/db --replSet rs0
  mongo --eval "rs.initiate()"
  ```
- Common issues:
  - No messages: verify `MONGO_URI`, DB name, and that you are inserting into `td_stock_tracker.signals` or `events`.
  - DNS SRV errors for `mongodb+srv://`: ensure `dnspython` is installed (included in `requirements.txt`).
  - WebSocket connection refused: check that uvicorn is running and port is open.

## Security & production notes

- Authentication: current WebSocket endpoints accept an optional `token` query param but do not validate it. Add JWT validation or token introspection before allowing subscriptions.
- TLS: use `wss://` in production. Terminate TLS at a proxy (nginx) or use a managed load balancer.
- Secrets: do NOT commit `.env` with credentials. Use a secret manager in production.

## Scaling

- Single-process (current): change-listener runs in-process and broadcasts to in-memory connections — simplest to run but limited to one instance.
- Multi-instance: add Redis pub/sub
  - Change-listener publishes events to Redis channels.
  - Each FastAPI instance subscribes to Redis and forwards messages to its local clients.
  - This allows horizontal scaling and decouples the listener from WebSocket instances.

## Next recommended improvements

1. Add JWT validation on websocket handshake (recommended before exposing to mobile clients).
2. Add Redis pub/sub for horizontal scaling if you expect many clients or multiple instances.
3. Optionally migrate to the official PyMongo asyncio API when you want a fully async change-listener.
4. Add monitoring, logging, and backpressure handling for production.

If you want, I can implement any of the next steps (auth, Redis wiring, demo client, or migration to async PyMongo). Tell me which and I'll proceed.

---

## Deployment (Kubernetes + ArgoCD)

I added a `deploy/infra/k8s` folder with Kubernetes manifests you can commit into your GitOps repo (or copy into the `infra/k8s` path referenced by your ArgoCD Application). The manifests include:

- `namespace.yaml` — `realtime` namespace
- `secret.yml` — template for runtime secrets (do NOT commit real secrets; edit locally and `kubectl apply -f secret.yml`)
- `configmap.yaml` — non-sensitive defaults (HOST, PORT)
- `deployment.yaml` — Deployment for the realtime service (image placeholder)
- `service.yaml` — ClusterIP service
- `ingress.yaml` — Traefik ingress configured for host `live-tracker-realtime.goodmanltd.com`
- `redis-argocd-application.yaml` — example ArgoCD Application to install Bitnami Redis via Helm into the `realtime` namespace (optional)

Quick notes:

- Replace `REPLACE_WITH_REGISTRY/realtime-service:latest` in `deployment.yaml` with your pushed image name.
- Use the `secret.yml` to store sensitive values (MONGO_URI, REDIS_URL, etc.). I left placeholders for you to fill.
- The ingress host is `live-tracker-realtime.goodmanltd.com` — update DNS and Traefik configuration accordingly.

## GitHub Actions

I added a sample workflow `.github/workflows/docker-publish.yml` that builds the `realtime_service` image and pushes to the registry using secrets:

- `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (or token)
- `DOCKERHUB_REPO` - image repo (`username/repo`)

Place those as GitHub repository secrets and the workflow will build and push on `main`.

## Applying manifests with ArgoCD

If your ArgoCD Application points to `infra/k8s`, commit the files into that path. Otherwise you can register `deploy/infra/k8s` as a new ArgoCD Application source. Example ArgoCD Application (added in `redis-argocd-application.yaml`) shows how to install Redis via Helm.

## Local test sequence

1. Build and push image (CI or local):

- Use the GitHub Actions workflow or run the Docker build/push locally.

2. Edit `deploy/infra/k8s/secret.yml` with real secrets and apply locally (or create a SealedSecret/ExternalSecret):

```bash
kubectl apply -f deploy/infra/k8s/secret.yml
kubectl apply -f deploy/infra/k8s/namespace.yaml
kubectl apply -f deploy/infra/k8s/configmap.yaml
kubectl apply -f deploy/infra/k8s/deployment.yaml
kubectl apply -f deploy/infra/k8s/service.yaml
kubectl apply -f deploy/infra/k8s/ingress.yaml
```

3. If using Redis chart via ArgoCD, apply the ArgoCD Application or install Redis manually with Helm:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm install redis bitnami/redis --namespace realtime --create-namespace
```

4. Verify pods and test the demo client:

```bash
kubectl port-forward svc/realtime-service -n realtime 8001:8001
python demo_client.py --url ws://localhost:8001/ws/notifications --symbols TD.TO
```

If you want, I can create the `deploy/` folder inside `infra/k8s` in your GitOps repo and add an ArgoCD Application entry like your existing `book-crossing-services` example so the service is managed by ArgoCD.

## Local secret generation

I added a `generate_secret.py` script to help create a real `secret.yml` locally from environment variables or a `.env` file. The canonical deploy path is `deploy/infra/k8s` in the repo — use that folder when generating secrets for cluster deployment. Example usage:

```bash
cd deploy/infra/k8s
# create a .env with MONGO_URI and MONGO_DB_NAME (and optional REDIS_URL, REDIS_CHANNEL, WS_JWT_SECRET)
python generate_secret.py --out secret.yml
# Do NOT commit secret.yml; apply it locally with:
kubectl apply -f secret.yml
```

This keeps secrets out of git while still making it easy to produce the Kubernetes Secret that the deployment expects.
