"""
websocket_manager.py — WebSocket Connection Manager
Manages all active WebSocket connections and provides broadcast utilities.
"""

import asyncio
import json
import logging
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger("smft.websocket")


class WebSocketManager:
    """
    Thread-safe WebSocket connection manager.
    Maintains a set of active connections and provides broadcast,
    unicast, and connection lifecycle management.
    """

    def __init__(self):
        self.connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.connections.add(websocket)
        logger.info(f"New connection. Total clients: {len(self.connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a disconnected WebSocket from the active set."""
        self.connections.discard(websocket)
        logger.info(f"Client disconnected. Total clients: {len(self.connections)}")

    def has_connections(self) -> bool:
        """Return True if there is at least one active connection."""
        return len(self.connections) > 0

    async def broadcast(self, data: dict) -> None:
        """
        Broadcast a JSON message to all connected clients.
        Dead connections are automatically removed.
        """
        if not self.connections:
            return

        message = json.dumps(data, default=str)
        dead: Set[WebSocket] = set()

        # Snapshot the connections set to avoid mutation during iteration
        async with self._lock:
            active = set(self.connections)

        for ws in active:
            try:
                await ws.send_text(message)
            except Exception as e:
                logger.debug(f"Broadcast failed for client (removing): {e}")
                dead.add(ws)

        # Clean up dead connections
        if dead:
            async with self._lock:
                self.connections -= dead

    async def send_to(self, websocket: WebSocket, data: dict) -> bool:
        """
        Send a JSON message to a specific WebSocket client.
        Returns False if the send failed.
        """
        try:
            await websocket.send_json(data)
            return True
        except Exception as e:
            logger.error(f"Failed to send to client: {e}")
            self.disconnect(websocket)
            return False

    async def broadcast_alert(self, alert: dict) -> None:
        """Broadcast a whale/system alert with type='whale_alert'."""
        await self.broadcast({
            "type": "whale_alert",
            "timestamp": alert.get("timestamp"),
            "data": alert,
        })

    def client_count(self) -> int:
        """Return the number of active connections."""
        return len(self.connections)
