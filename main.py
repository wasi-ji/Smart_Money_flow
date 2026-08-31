"""
Smart Money Flow Terminal Pro — main.py
FastAPI application with WebSocket broadcasting
Orchestrates all engines and streams data to connected clients
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import settings
from database import Database
from websocket_manager import WebSocketManager
from capital_flow_engine import CapitalFlowEngine
from market_scanner import MarketScanner
from dominance_engine import DominanceEngine
from whale_detector import WhaleDetector
from funding_engine import FundingEngine
from ranking_engine import RankingEngine
from sector_rotation import SectorRotationEngine

# ── Logging Setup ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("smft.main")


# ══════════════════════════════════════════════════════
# LIFESPAN — startup / shutdown
# ══════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize all components on startup, clean up on shutdown."""
    logger.info("=== Smart Money Flow Terminal Pro starting… ===")

    # Init database
    await app.state.db.initialize()
    logger.info("Database initialized")

    # Start all background engines
    tasks = [
        asyncio.create_task(app.state.market_scanner.run(), name="market_scanner"),
        asyncio.create_task(app.state.dominance_engine.run(), name="dominance_engine"),
        asyncio.create_task(app.state.funding_engine.run(), name="funding_engine"),
        asyncio.create_task(app.state.whale_detector.run(), name="whale_detector"),
        asyncio.create_task(app.state.sector_engine.run(), name="sector_rotation"),
        asyncio.create_task(broadcast_loop(app), name="broadcast_loop"),
    ]
    app.state.background_tasks = tasks
    logger.info(f"Started {len(tasks)} background tasks")

    yield  # ── app is running ──

    # Shutdown
    logger.info("Shutting down…")
    for task in app.state.background_tasks:
        task.cancel()
    await asyncio.gather(*app.state.background_tasks, return_exceptions=True)
    await app.state.market_scanner.close()
    await app.state.db.close()
    logger.info("Shutdown complete")


# ══════════════════════════════════════════════════════
# APP FACTORY
# ══════════════════════════════════════════════════════
def create_app() -> FastAPI:
    app = FastAPI(
        title="Smart Money Flow Terminal Pro",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS — allow all origins for development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Shared state
    db = Database(settings.DB_PATH)
    ws_manager = WebSocketManager()
    market_scanner = MarketScanner(settings)
    flow_engine = CapitalFlowEngine(market_scanner)
    dominance_engine = DominanceEngine(market_scanner, settings)
    whale_detector = WhaleDetector(market_scanner, ws_manager, settings)
    funding_engine = FundingEngine(settings)
    ranking_engine = RankingEngine(flow_engine)
    sector_engine = SectorRotationEngine(market_scanner)

    app.state.db = db
    app.state.ws_manager = ws_manager
    app.state.market_scanner = market_scanner
    app.state.flow_engine = flow_engine
    app.state.dominance_engine = dominance_engine
    app.state.whale_detector = whale_detector
    app.state.funding_engine = funding_engine
    app.state.ranking_engine = ranking_engine
    app.state.sector_engine = sector_engine

    return app


app = create_app()


# ══════════════════════════════════════════════════════
# STATIC FILES — serve frontend
# ══════════════════════════════════════════════════════
try:
    app.mount("/static", StaticFiles(directory="../frontend"), name="static")
except Exception:
    pass  # Frontend dir may not exist in some deployments


@app.get("/")
async def serve_frontend():
    try:
        return FileResponse("../frontend/index.html")
    except Exception:
        return {"message": "Smart Money Flow Terminal Pro API", "version": "1.0.0"}


# ══════════════════════════════════════════════════════
# REST ENDPOINTS
# ══════════════════════════════════════════════════════
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connected_clients": len(app.state.ws_manager.connections),
    }


@app.get("/api/flow-scores")
async def get_flow_scores():
    """Return latest capital flow scores for all tracked assets."""
    return app.state.ranking_engine.get_rankings()


@app.get("/api/dominance")
async def get_dominance():
    """Return latest dominance data."""
    return app.state.dominance_engine.get_latest()


@app.get("/api/funding")
async def get_funding():
    """Return latest funding rates."""
    return app.state.funding_engine.get_latest()


@app.get("/api/whale-alerts")
async def get_whale_alerts():
    """Return recent whale alerts."""
    return app.state.whale_detector.get_recent_alerts()


@app.get("/api/sectors")
async def get_sectors():
    """Return sector rotation data."""
    return app.state.sector_engine.get_latest()


# ══════════════════════════════════════════════════════
# WEBSOCKET ENDPOINT
# ══════════════════════════════════════════════════════
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket endpoint.
    1. Accept connection
    2. Send full snapshot of current state
    3. Register for broadcast loop
    4. Handle client messages (ping/pong, subscriptions)
    """
    await app.state.ws_manager.connect(websocket)
    client_id = id(websocket)
    logger.info(f"WebSocket client connected: {client_id}")

    try:
        # Send initial snapshot
        snapshot = await build_snapshot(app)
        await websocket.send_json(snapshot)

        # Keep alive — handle incoming messages
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                msg = json.loads(data)
                await handle_client_message(websocket, msg, app)
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "ping", "timestamp": int(time.time() * 1000)})

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket error for client {client_id}: {e}")
    finally:
        app.state.ws_manager.disconnect(websocket)


async def handle_client_message(websocket: WebSocket, msg: dict, app: FastAPI):
    """Handle incoming client messages (pong, subscription changes)."""
    msg_type = msg.get("type")
    if msg_type == "pong":
        pass  # Heartbeat acknowledgment
    elif msg_type == "subscribe":
        # Future: allow clients to subscribe to specific symbols
        pass
    elif msg_type == "get_snapshot":
        snapshot = await build_snapshot(app)
        await websocket.send_json(snapshot)


async def build_snapshot(app: FastAPI) -> dict:
    """Build a complete state snapshot for new connections."""
    flow_scores = app.state.ranking_engine.get_rankings()
    market_data = app.state.market_scanner.get_latest_prices()
    dominance = app.state.dominance_engine.get_latest()
    funding = app.state.funding_engine.get_latest()
    oi_data = app.state.market_scanner.get_oi_data()
    sectors = app.state.sector_engine.get_latest()
    regime = app.state.flow_engine.get_risk_regime()

    return {
        "type": "full_snapshot",
        "timestamp": int(time.time() * 1000),
        "data": {
            "market": market_data,
            "flow_scores": flow_scores,
            "dominance": dominance,
            "funding": funding,
            "oi": oi_data,
            "sectors": sectors,
            "regime": regime,
        },
    }


# ══════════════════════════════════════════════════════
# BROADCAST LOOP
# ══════════════════════════════════════════════════════
async def broadcast_loop(app: FastAPI):
    """
    Main broadcast loop — runs every second, collects data from all
    engines and broadcasts updates to all connected WebSocket clients.
    """
    logger.info("Broadcast loop started")
    tick = 0

    while True:
        try:
            await asyncio.sleep(1.0)
            tick += 1

            if not app.state.ws_manager.has_connections():
                continue

            # Always broadcast: market prices + flow scores
            market_data = app.state.market_scanner.get_latest_prices()
            if market_data:
                await app.state.ws_manager.broadcast({
                    "type": "market_update",
                    "timestamp": int(time.time() * 1000),
                    "data": market_data,
                })

            flow_scores = app.state.ranking_engine.get_rankings()
            if flow_scores:
                await app.state.ws_manager.broadcast({
                    "type": "flow_scores",
                    "timestamp": int(time.time() * 1000),
                    "data": flow_scores,
                })

            # Every 5 seconds: funding rates
            if tick % 5 == 0:
                funding = app.state.funding_engine.get_latest()
                if funding:
                    await app.state.ws_manager.broadcast({
                        "type": "funding_update",
                        "timestamp": int(time.time() * 1000),
                        "data": funding,
                    })

            # Every 10 seconds: OI + dominance
            if tick % 10 == 0:
                oi_data = app.state.market_scanner.get_oi_data()
                if oi_data:
                    await app.state.ws_manager.broadcast({
                        "type": "oi_update",
                        "timestamp": int(time.time() * 1000),
                        "data": oi_data,
                    })

                dominance = app.state.dominance_engine.get_latest()
                if dominance:
                    await app.state.ws_manager.broadcast({
                        "type": "dominance",
                        "timestamp": int(time.time() * 1000),
                        "data": dominance,
                    })

            # Every 15 seconds: sector rotation + risk regime
            if tick % 15 == 0:
                sectors = app.state.sector_engine.get_latest()
                if sectors:
                    await app.state.ws_manager.broadcast({
                        "type": "sector_update",
                        "timestamp": int(time.time() * 1000),
                        "data": sectors,
                    })

                regime = app.state.flow_engine.get_risk_regime()
                if regime:
                    await app.state.ws_manager.broadcast({
                        "type": "risk_regime",
                        "timestamp": int(time.time() * 1000),
                        "data": regime,
                    })

            # Reset tick to prevent overflow
            if tick >= 10000:
                tick = 0

        except asyncio.CancelledError:
            logger.info("Broadcast loop cancelled")
            break
        except Exception as e:
            logger.error(f"Broadcast loop error: {e}", exc_info=True)
            await asyncio.sleep(2)


# ══════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
        ws_ping_interval=20,
        ws_ping_timeout=30,
    )
