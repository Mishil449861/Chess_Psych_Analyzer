import requests
import chess.pgn
import io
from db import insert_game_data
from engine import chess_engine

def fetch_lichess_games(username: str, max_games: int = 200):
    url = f"https://lichess.org/api/games/user/{username}"
    params = {
        "max": max_games,
        "evals": "true",
        "clocks": "true",
        "opening": "true"
    }
    headers = {"Accept": "application/x-chess-pgn"}
    
    print(f"Fetching games for {username}...")
    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()
    return response.text

def process_and_store_games(username: str, pgn_text: str):
    pgn_io = io.StringIO(pgn_text)
    
    while True:
        game = chess.pgn.read_game(pgn_io)
        if game is None:
            break
            
        headers = game.headers
        game_id = headers.get("Site", "").split("/")[-1]
        
        # Determine player color and rating
        if headers.get("White", "").lower() == username.lower():
            color = "White"
            user_rating = int(headers.get("WhiteElo", 1500) or 1500)
            opp_rating = int(headers.get("BlackElo", 1500) or 1500)
        else:
            color = "Black"
            user_rating = int(headers.get("BlackElo", 1500) or 1500)
            opp_rating = int(headers.get("WhiteElo", 1500) or 1500)

        game_data = {
            "id": game_id,
            "color": color,
            "opp_rating": opp_rating,
            "eco": headers.get("ECO", "?"),
            "result": headers.get("Result", "*")
        }
        
        board = game.board()
        moves_data = []
        last_eval = 0
        last_clock = None
        
        for i, node in enumerate(game.mainline()):
            move = node.move
            san = board.san(move)
            fen_before = board.fen()
            
            # Extract Eval
            eval_after = node.eval()
            if eval_after is not None:
                current_eval = eval_after.white().score(mate_score=10000)
            else:
                # Fallback to engine if PGN lacks eval
                board.push(move)
                current_eval = chess_engine.evaluate_position(board)
                board.pop()
                
            # Time spent
            clock = node.clock()
            time_spent = (last_clock - clock) if (last_clock and clock) else 0
            last_clock = clock
            
            # Blunder detection threshold scales with rating
            blunder_threshold = 150 if user_rating < 1600 else 100
            
            is_blunder = False
            if color == "White" and (last_eval - current_eval) > blunder_threshold:
                is_blunder = True
            elif color == "Black" and (current_eval - last_eval) > blunder_threshold:
                is_blunder = True

            # Only track the user's moves
            if board.turn == (chess.WHITE if color == "White" else chess.BLACK):
                moves_data.append((
                    game_id, i, color, fen_before, san, 
                    last_eval, current_eval, time_spent, is_blunder
                ))
            
            board.push(move)
            last_eval = current_eval

        insert_game_data(username, "lichess", user_rating, game_data, moves_data)
        print(f"Processed game {game_id} ({len(moves_data)} user moves)")

if __name__ == "__main__":
    test_user = "EricRosen" # Example Lichess user
    pgn_data = fetch_lichess_games(test_user, max_games=10)
    process_and_store_games(test_user, pgn_data)