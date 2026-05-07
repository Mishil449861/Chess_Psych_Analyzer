import sqlite3
import json

DB_PATH = "chess_psych.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            platform TEXT,
            rating INTEGER
        );
        
        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            username TEXT,
            color TEXT,
            opponent_rating INTEGER,
            opening_eco TEXT,
            result TEXT,
            FOREIGN KEY(username) REFERENCES users(username)
        );
        
        CREATE TABLE IF NOT EXISTS moves (
            move_id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT,
            move_number INTEGER,
            player_color TEXT,
            fen TEXT,
            san TEXT,
            eval_before INTEGER,
            eval_after INTEGER,
            time_spent REAL,
            is_blunder BOOLEAN,
            FOREIGN KEY(game_id) REFERENCES games(game_id)
        );
    """)
    conn.commit()
    conn.close()

def insert_game_data(username, platform, rating, game_data, moves_data):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Upsert user
    cursor.execute("""
        INSERT OR REPLACE INTO users (username, platform, rating) 
        VALUES (?, ?, ?)
    """, (username, platform, rating))
    
    # Insert game
    cursor.execute("""
        INSERT OR IGNORE INTO games (game_id, username, color, opponent_rating, opening_eco, result)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (game_data['id'], username, game_data['color'], game_data['opp_rating'], game_data['eco'], game_data['result']))
    
    # Insert moves
    cursor.executemany("""
        INSERT INTO moves (game_id, move_number, player_color, fen, san, eval_before, eval_after, time_spent, is_blunder)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, moves_data)
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized.")