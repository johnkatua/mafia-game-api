"""
Websocket-based Mafia Game Server

This FastAPI server manages real-time multiplayer Mafia game. It allows users to:
    - Create a new game session with a unique Game ID.
    - Join an existing game via Websocket
    - Maintain game state and broadcast updates to all connected players

Websocket handles real-time communication, ensuring all players receive updates on game events.
"""
import asyncio
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
async def create_game(player_name: str):
    """Creates a new game session and returns a unique Game ID."""
    game_id = str(random.randint(000000, 999999)
                  )  # Generate a 6-digit unique game ID
    games[game_id] = {
        "host": player_name,
        "players": [],
        "state": "waiting",
        "cards": [],
        "selected_cards": {},
        "eliminated": set(),
        "votes": {}
    }

    return {
        "game_id": game_id,
        "join": f"{BASE_URL}/join/{game_id}",
        "host": player_name
    }


@app.post("/restart/{game_id}")
async def restart_game(game_id: str):
    """Resets the game state while keeping the same players and game ID."""
    if game_id not in games:
        return {
            "error": "Game not found"
        }

    # Reset all game states except players
    games[game_id].update({
        "state": "waiting",
        "cards": [],
        "selected_cards": {},
        "eliminated": set(),
        "votes": {}
    })

    # Notify players about the game restart
    for ws in game_connections[game_id].values():
        await ws.send_json({
            "message": "Game has been restarted! Select new cards when the game starts."
        })

    return {"message": "Game restarted successfully"}


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

                    # Set game state to selecting phase
                    games[game_id]["state"] = "selecting"

                elif data["action"] == "select_card":
                    player_name = data["player"]
                    card_id = data["card_id"]
                    active_card = games[game_id]["cards"][card_id]

                    # Ensure the card is not already picked
                    if active_card["selected"]:
                        await websocket.send_json({"error": "Card already selected!"})
                        continue

                    # Assign the card to the player
                    active_card["selected"] = True
                    active_card["player_name"] = player_name
                    games[game_id]["selected_card"][player_name] = active_card["card_value"]

                    # Send **only the player** their assigned role
                    await websocket.send_json({
                        "message": "You have selected your card!",
                        "your_role": games[game_id]["cards"][card_id]["card_value"]
                    })

                    # Check if all players have selected cards
                    if len(games[game_id]["selected_cards"]) == len(games[game_id]["players"]):
                        # Move to game phase
                        games[game_id]["state"] = "playing"

                        # Notify mafias who their teammates are
                        mafia_players = [
                            p for p, role in games[game_id]["selected_cards"].items()
                            if role == "mafia"
                        ]

                        if len(mafia_players) > 1:
                            mafia_message = {
                                "message": "You are Mafia. Your teammates are:",
                                "mafia_team": mafia_players
                            }
                            for mafia in mafia_players:
                                mafia_ws = game_connections[game_id].get(mafia)
                                if mafia_ws:
                                    await mafia_ws.send_json(mafia_message)

                        # Move to game phase
                        games[game_id]["state"] = "discussion"
                        await start_discussion_phase(game_id)

                elif data["action"] == "vote":
                    voted_player = data["voted_player"]
                    if voted_player not in games[game_id]["players"] or voted_player in games[game_id]["eliminated"]:
                        await websocket.send_json({
                            "error": "Invalid vote!"
                        })
                        continue

                    games[game_id]["votes"][player_name] = voted_player

                    if len(games[game_id]["votes"]) == len(games[game_id]["players"]) - len(games[game_id]["eliminated"]):
                        await handle_voting_results(game_id)

                # Send updated state (excluding roles) to all players
                game_state = {
                    "state": games[game_id]["state"],
                    "players": list(games[game_id]["players"].keys()),
                    "cards": [
                        {
                            "card_id": card["card_id"],
                            "selected": card["selected"],
                            "player_name": card["player_name"]
                        }
                        for card in games[game_id]["cards"]
                    ]
                }
                # Broadcast updated game state to all players
                for ws in game_connections[game_id].values():
                    await ws.send_json(game_state)
    except WebSocketDisconnect:
        game_connections[game_id].remove(websocket)


async def start_discussion_phase(game_id: str):
    """Starts a discussion phase where each player has 2 mins"""
    total_time = len(games[game_id]["players"]) * 2

    for ws in game_connections[game_id].values():
        await ws.send_json({
            "message": f"Discussion time started! Total time: {total_time} minutes."
        })

    await asyncio.sleep(total_time * 60)  # Wait for the discussion time to end

    games[game_id]["state"] = "voting"
    for ws in game_connections[game_id].values():
        await ws.send_json({
            "message": "Discussion over! Time to vote."
        })


async def handle_voting_results(game_id: str):
    """Handles voting, eliminates the most-voted player, and checks for winners."""
    vote_count = defaultdict(int)

    # Count votes
    for player in games[game_id]["votes"].values():
        vote_count[player] += 1

    # Find player with max votes
    eliminated_player = max(vote_count, key=vote_count.get)
    games[game_id]["eliminated"].add(eliminated_player)
    role = games[game_id]["selected_cards"][eliminated_player]

    # Notify all players of elimination result
    for ws in game_connections[game_id].values():
        await ws.send_json({
            "message": f"{eliminated_player} has been eliminated!",
            "eliminated_role": role
        })

    # Check win conditions
    mafia_remaining = sum(
        1 for p in games[game_id]["selected_cards"] if p not in games[game_id]["eliminated"] and
        games[game_id]["selected_cards"][p] == "mafia"
    )
    civilian_remaining = sum(
        1 for p in games[game_id]["selected_cards"] if p not in games[game_id]["eliminated"] and
        games[game_id]["selected_cards"][p] == "civilian"
    )

    if mafia_remaining >= civilian_remaining:
        winner = "Mafia"
    elif mafia_remaining == 0:
        winner = "Civilians"
    else:
        winner = None

    if winner:
        for ws in game_connections[game_id].values():
            await ws.send_json({
                "message": f"Game Over! {winner} win!"
            })
        games.pop(game_id)  # Remove game data
