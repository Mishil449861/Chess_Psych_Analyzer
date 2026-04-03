import requests

OLLAMA_URL  = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "llama3"

_PIECE_MAP = {
    'N': "Knight", 'B': "Bishop", 'R': "Rook",
    'Q': "Queen",  'K': "King",   'O': "King (Castling)",
}

def _piece_name(san: str) -> str:
    if not san:
        return "Unknown Piece"
    return _PIECE_MAP.get(san[0], "Pawn")


def generate_explanation(log: dict) -> str:
    """
    Build a two-sentence psychological profile from a move log entry.

    Required log keys (all populated by app.py):
        move, tag, phase, tactics, delta, absolute_eval, cpu_color
    """
    san        = log.get("move",         "?")
    piece      = _piece_name(san)
    cpu_color  = log.get("cpu_color",    "Unknown")
    phase      = log.get("phase",        "Unknown")
    tactics    = log.get("tactics",      "Unknown")
    delta      = log.get("delta",        0)
    abs_eval   = log.get("absolute_eval", 0) / 100.0
    tag        = log.get("tag",          "Unknown")

    if abs_eval > 0:
        advantage = f"White leads by {abs(abs_eval):.1f} pawns"
    elif abs_eval < 0:
        advantage = f"Black leads by {abs(abs_eval):.1f} pawns"
    else:
        advantage = "Dead even"

    prompt = f"""Act as a professional chess psychologist and behavioral profiler.

CRITICAL RULES:
1. Start immediately with the analysis — no introductions, no filler.
2. EXACTLY TWO SENTENCES. No more, no less.
3. Use clinical language only: "prophylaxis", "tension", "positional discomfort", "over-extended", "practical chances".
4. Analyze strictly from the {cpu_color.upper()} side's perspective.

Sentence 1 (The Mask): Based on the momentum shift and move quality, evaluate the opponent's composure and risk-tolerance right now.
Sentence 2 (The Intent): Explain the concrete strategic goal of this {piece} move ({san}) and what {cpu_color} is preparing next.

GAME DATA:
  Opponent color   : {cpu_color}
  Game phase       : {phase}
  Advantage        : {advantage}
  Tactical nature  : {tactics}
  Momentum shift   : {delta:+d} centipawns
  Behavioral tag   : {tag}
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model":  OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.5,
                    "num_predict": 150,
                },
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except requests.exceptions.ConnectionError:
        return "Analysis offline — Ollama is not running."
    except Exception as e:
        return f"Analysis error: {e}"
