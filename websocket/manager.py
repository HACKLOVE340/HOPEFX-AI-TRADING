# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
import asyncio
import json

import websockets


class WebSocketManager:
    def __init__(self):
        self.connections = set()

    async def register(self, websocket):
        self.connections.add(websocket)

    async def unregister(self, websocket):
        self.connections.remove(websocket)

    async def connection_handler(self, websocket, path):
        await self.register(websocket)
        try:
            async for message in websocket:
                await self.broadcast(message)
        finally:
            await self.unregister(websocket)

    async def broadcast(self, message):
        if self.connections:  # Don't send to empty group
            message = json.dumps(message)
            await asyncio.wait([user.send(message) for user in self.connections])

    def start_server(self, host="localhost", port=8765):
        server = websockets.serve(self.connection_handler, host, port)
        asyncio.get_event_loop().run_until_complete(server)
        asyncio.get_event_loop().run_forever()


# Example usage:
if __name__ == "__main__":
    ws_manager = WebSocketManager()
    ws_manager.start_server()
