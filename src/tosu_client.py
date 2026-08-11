import asyncio
import json
import threading

import websockets

from config import TOSU_WS_URL


class TosuClient:
    """Background thread holding a persistent websocket connection to tosu,
    calling `on_update(data)` for every state push. Auto-reconnects if tosu
    isn't running yet or the connection drops (e.g. osu! restarted).

    tosu exposes no actual osu! process start/end timestamp, so each fresh
    connection is treated as the start of a new "game session" (osu! open
    to close) via `on_connect` - reconnecting after a drop means osu! (or
    tosu) restarted, which is exactly the boundary we want to mark. Symmetrically,
    `on_disconnect` fires whenever a connection that had been established goes
    away (osu!/tosu closed, or we're shutting down ourselves), marking that
    same session's end.
    """

    def __init__(self, on_update, on_connect=None, on_disconnect=None):
        self.on_update = on_update
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._stop = threading.Event()

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        asyncio.run(self._loop())

    async def _loop(self):
        while not self._stop.is_set():
            connected = False
            try:
                async with websockets.connect(TOSU_WS_URL, ping_interval=None) as ws:
                    connected = True
                    if self.on_connect:
                        self.on_connect()
                    async for message in ws:
                        if self._stop.is_set():
                            break
                        try:
                            data = json.loads(message)
                        except json.JSONDecodeError:
                            continue
                        self.on_update(data)
            except (ConnectionRefusedError, OSError, websockets.exceptions.WebSocketException):
                # tosu not running / osu! not open yet - retry quietly
                await asyncio.sleep(3)
            finally:
                if connected and self.on_disconnect:
                    self.on_disconnect()
