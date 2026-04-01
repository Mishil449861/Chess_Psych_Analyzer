import requests

# NEW: We translate the piece in Python so the AI doesn't have to guess!
def get_piece_name(san_move):
    if not san_move: return "Unknown Piece"
    char = san_move[0]
    if char == 'N': return "Knight"
    elif char == 'B': return "Bishop"
    elif char == 'R': return "Rook"
    elif char == 'Q': return "Queen"
    elif char == 'K': return "King"
    elif char == 'O': return "King (Castling)"
    else: return "Pawn"

def generate_explanation(log):
    san_move = log.get('move', 'Unknown')
    piece_name = get_piece_name(san_move)

    prompt = f"""Act as a ruthless, gritty psychological profiler analyzing a hostile chess opponent. 
    
    CRITICAL RULES:
    1. NEVER use introductory filler phrases like "Here is my analysis", "My observations are", or "The AI is exhibiting".
    2. Start the very first word with your psychological breakdown.
    3. Keep it to exactly two punchy, intense sentences. 
    4. Focus on their fear, arrogance, calculation, or panic. 

    Game Phase: {log.get('phase', 'Unknown')}
    Piece Moved: {piece_name} (Exact notation: {san_move})
    Momentum Shift: {log.get('delta')} points
    Detected State: {log.get('tag')}
    """

    try:
        response = requests.post("http://127.0.0.1:11434/api/generate", json={
            "model": "llama3",
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "num_predict": 120 
            }
        })
        
        return response.json()["response"].strip()
    except Exception as e:
        return f"Insight Error: {e}"