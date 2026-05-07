import sqlite3
import chess
import requests
import time

DB_PATH = "chess_psych.db"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "qwen2.5-coder:7b"

def _call_llm(prompt: str, max_tokens: int = 60) -> str:
    """Helper to call Ollama safely."""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL, 
                "prompt": prompt, 
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": max_tokens}
            },
            timeout=120 
        )
        if response.status_code == 200:
            return response.json().get("response", "").strip()
        return "Insight generation failed."
    except Exception as e:
        return "Coach is currently offline."

def generate_cluster_summary(cluster_moves: list) -> str:
    examples_text = ""
    piece_map = {'N': 'Knight', 'B': 'Bishop', 'R': 'Rook', 'Q': 'Queen', 'K': 'King', 'P': 'Pawn'}
    
    for m in cluster_moves[:4]:
        drop = abs(m['eval_before'] - m['eval_after']) / 100.0
        piece_name = piece_map.get(m['san'][0] if m['san'][0] in piece_map else 'P', 'Pawn')
        
        tactics = "a standard move"
        if '+' in m['san']: tactics = "a checking move"
        elif 'x' in m['san']: tactics = "a capture"
        
        examples_text += f"- Action: Played {piece_name} ({m['san']}) as {tactics}. Result: Blundered {drop:.1f} pawns.\n"
    
    prompt = f"""You are a blunt, highly technical chess coach. Look at this data summarizing a specific cluster of blunders made by a player.
Data:
{examples_text}

Write EXACTLY ONE concise, analytical sentence describing this specific pattern. 
Rule 1: Focus on the specific piece moved and the type of action.
Rule 2: Sound like a real chess player diagnosing a specific blindspot. Do NOT give generic advice. 
Rule 3: Start your sentence directly with "You tend to..." """
    
    return _call_llm(prompt, 60)

def generate_persona_title(insights: list) -> str:
    insights_text = "\n".join([i['text'] for i in insights])
    prompt = f"""Based on these specific chess weaknesses, give this player a 2 to 4 word "Boss Title" or Persona. 
Weaknesses:
{insights_text}

Examples of good titles: "The Careless Aggressor", "The Glass Cannon", "The Queen Blunderer".
Write ONLY the title, nothing else."""
    return _call_llm(prompt, 15)

def get_player_profile(username: str) -> dict:
    """Called by app.py to load the user's historical profile."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT fen, san, eval_before, eval_after 
        FROM moves 
        JOIN games ON moves.game_id = games.game_id
        WHERE games.username = ? AND moves.is_blunder = 1
    """, (username,))
    
    blunders = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    if len(blunders) < 10:
        return {"error": "Not enough game history found. Run ingest.py first."}

    clusters_dict = {}
    for b in blunders:
        san = b['san']
        piece = san[0] if san[0] in 'NBRQK' else 'P'
        if piece not in clusters_dict:
            clusters_dict[piece] = []
        clusters_dict[piece].append(b)
        
    sorted_groups = sorted(clusters_dict.values(), key=len, reverse=True)
    top_clusters = {i: group for i, group in enumerate(sorted_groups[:3])}
    
    profile_data = {"insights": []}
    
    for label, moves in top_clusters.items():
        piece_char = moves[0]['san'][0] if moves[0]['san'][0] in 'NBRQK' else 'P'
        summary = generate_cluster_summary(moves)
        profile_data["insights"].append({
            "piece": piece_char,
            "text": summary,
            "count": len(moves)
        })
        
    profile_data["persona_title"] = generate_persona_title(profile_data["insights"])
    profile_data["total_blunders"] = len(blunders)
    
    return profile_data