import requests

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
    
    eval_score = log.get('absolute_eval', 0) / 100.0
    advantage = f"White by {abs(eval_score)} pawns" if eval_score > 0 else f"Black by {abs(eval_score)} pawns" if eval_score < 0 else "Dead even"

    prompt = f"""Act as a professional chess psychologist and Grandmaster commentator. 
    
    CRITICAL RULES:
    1. NEVER use filler phrases. Start immediately with the analysis.
    2. EXACTLY TWO SENTENCES.
    3. NO MELODRAMA. Do not use words like "fear", "desperation", "panic", or "furious". Use professional chess terminology like "prophylaxis", "tension", "positional discomfort", "over-extended", "practical chances", or "solidifying".
    4. Sentence 1: Analyze their mindset based on the momentum shift. Are they feeling positional pressure, confidently following opening preparation, or reacting to a complication?
    5. Sentence 2: Explain their concrete board intention using the "Tactical Nature" data and what it means for the position.

    HARD DATA TO ANALYZE:
    Game Phase: {log.get('phase', 'Unknown')}
    Current Absolute Advantage: {advantage}
    Piece Moved: {piece_name} (Notation: {san_move})
    Tactical Nature of Move: {log.get('tactics', 'Unknown')}
    Momentum Shift: {log.get('delta')} centipawns
    Detected State: {log.get('tag')}
    """

    try:
        response = requests.post("http://127.0.0.1:11434/api/generate", json={
            "model": "llama3",
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.5, 
                "num_predict": 120 
            }
        })
        
        return response.json()["response"].strip()
    except Exception as e:
        return f"Insight Error: {e}"