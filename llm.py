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

IMPORTANT RULES:
1. Start immediately — no introductions.
2. Use exactly TWO sentences.
3. Keep language simple and easy to understand.
4. Do NOT sound clinical or robotic.
5. Do NOT predict exact moves. Instead, describe ideas or plans the opponent may be aiming for.
6. Focus on what the opponent is likely trying to achieve next (plans, threats, or strategy).
7. Write from the perspective of explaining the opponent's thinking in plain language.
8. Analyze strictly from the {cpu_color.upper()} side's perspective.

Sentence 1 (The Mask): Explain how the opponent likely feels about the position and what is influencing their decisions right now.
Sentence 2 (The Intent): Explain what kind of movement they may be going for with this {piece} move ({san}) and what {cpu_color} is preparing next (for example: attacking the king, improving piece activity, simplifying, defending weaknesses).

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
