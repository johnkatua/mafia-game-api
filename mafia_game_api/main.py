"""Entry point"""
import uuid
from typing import Dict, List
from collections import defaultdict
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active games
games: Dict[str, Dict] = {}

# Store active websocket connections per game
game_connections: Dict[str, List[WebSocket]] = defaultdict(list)


@app.post("/create_game")
async def create_game():
    """Creates a new game session and returns a unique Game ID."""
    game_id = str(uuid.uuid4())[:6]  # Generate a short unique game ID
    games[game_id] = {
        "players": [],
        "state": "waiting"
    }
