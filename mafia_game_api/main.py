"""
Websocket-based Mafia Game Server

This FastAPI server manages real-time multiplayer Mafia game. It allows users to:
    - Create a new game session with a unique Game ID.
    - Join an existing game via Websocket
    - Maintain game state and broadcast updates to all connected players

Websocket handles real-time communication, ensuring all players receive updates on game events.
"""
import random
from typing import Dict, List
from collections import defaultdict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_URL: str = "http://localhost:3000"

# Store active games
games: Dict[str, Dict] = {}

# Store active websocket connections per game
game_connections: Dict[str, List[WebSocket]] = defaultdict(list)


@app.post("/create_game")
async def create_game():
    """Creates a new game session and returns a unique Game ID."""
    game_id = str(random.randint(000000, 999999)
                  )  # Generate a 6-digit unique game ID
    games[game_id] = {
        "players": [],
        "state": "waiting",
        "cards": [],
        "selected_cards": {}
    }

    return {
        "game_id": game_id,
        "join": f"{BASE_URL}/join/{game_id}"
    }


@app.websocket("/ws/{game_id}")
async def websocket_endpoint(game_id: str, websocket: WebSocket):
    """Handles real-time communication for a specific game."""
    await websocket.accept()
    game_connections[game_id].append(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            if "action" in data:
                if data["action"] == "join":
                    player_name = data["player"]
                    games[game_id]["players"].append(player_name)

                elif data["action"] == "start_game":
                    players = games[game_id]["players"]
                    if len(players) < 4:  # Ensure minimum players before starting
                        await websocket.send_json({
                            "error": "Not enough players to start the game!"
                        })
                        continue

                    # Create shuffled roles
                    # 25% should be mafia
                    num_mafia = max(1, len(players) // 4)
                    roles = ["mafia"] * num_mafia + \
                        ["civilian"] * (len(players) - num_mafia)
                    random.shuffle(roles)

                    # Create face-down cards (no player assigned yet)
                    games[game_id]["cards"] = [
                        {
                            "card_id": index,
                            "selected": False,
                            "player_name": None,
                            "card_value": roles[index]
                        }
                        for index in range(len(players))
                    ]

                # Broadcast updated game state to all players
                for connection in game_connections[game_id]:
                    await connection.send_json(games[game_id])
    except WebSocketDisconnect:
        game_connections[game_id].remove(websocket)
