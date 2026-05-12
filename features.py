"""Per-move feature extraction.

Given a position and a move, build a structured feature dict that captures
*why* the move might be a blunder: which piece moved, was it a capture,
did it leave pieces hanging, did it expose the king, etc.

These features feed both the database (stored as JSON per blunder) and
the clustering step in patterns.py.
"""
import chess
from typing import Dict, Any

PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}
PIECE_NAMES = {
    chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
    chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king",
}


def phase_of(board: chess.Board) -> str:
    """opening / middlegame / endgame based on move count + remaining material."""
    if board.fullmove_number < 10:
        return "opening"
    non_pawn = sum(
        len(board.pieces(pt, chess.WHITE)) + len(board.pieces(pt, chess.BLACK))
        for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
    )
    if non_pawn <= 6:
        return "endgame"
    return "middlegame"


def hanging_pieces(board: chess.Board, color: bool) -> list:
    """Squares of `color` pieces that are attacked and not adequately defended."""
    out = []
    for square, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type == chess.KING:
            continue
        attackers = board.attackers(not color, square)
        if not attackers:
            continue
        defenders = board.attackers(color, square)
        if not defenders:
            out.append(square)
            continue
        # Crude SEE: cheapest attacker vs piece value
        min_attacker_val = min(
            PIECE_VALUES[board.piece_at(s).piece_type] for s in attackers
        )
        if min_attacker_val < PIECE_VALUES[piece.piece_type]:
            out.append(square)
    return out


def king_zone_attackers(board: chess.Board, king_color: bool) -> int:
    """Squares adjacent to the king attacked by the opponent."""
    king_sq = board.king(king_color)
    if king_sq is None:
        return 0
    enemy = not king_color
    count = 0
    for sq in chess.SQUARES:
        if sq == king_sq:
            continue
        if chess.square_distance(sq, king_sq) <= 1 and board.is_attacked_by(enemy, sq):
            count += 1
    return count


def material_balance(board: chess.Board) -> int:
    """White material minus Black material, in pawn units."""
    s = 0
    for pt, val in PIECE_VALUES.items():
        s += val * len(board.pieces(pt, chess.WHITE))
        s -= val * len(board.pieces(pt, chess.BLACK))
    return s


def extract_move_features(
    fen_before: str,
    fen_after: str,
    san: str,
    uci: str,
    time_spent: float = None,
    eval_before: int = 0,
    eval_after: int = 0,
    side: str = "white",
    eco: str = None,
) -> Dict[str, Any]:
    """Build the feature dict for one move."""
    board_before = chess.Board(fen_before)
    board_after = chess.Board(fen_after)

    move = chess.Move.from_uci(uci)
    piece_moved = board_before.piece_at(move.from_square)
    piece_name = PIECE_NAMES.get(piece_moved.piece_type, "unknown") if piece_moved else "unknown"

    is_capture = board_before.is_capture(move)
    is_check = board_after.is_check()

    user_color = chess.WHITE if side == "white" else chess.BLACK

    hanging_before = len(hanging_pieces(board_before, user_color))
    hanging_after = len(hanging_pieces(board_after, user_color))

    king_atk_before = king_zone_attackers(board_before, user_color)
    king_atk_after = king_zone_attackers(board_after, user_color)

    mat_before = material_balance(board_before)
    mat_after = material_balance(board_after)
    mat_delta = mat_after - mat_before
    if side == "black":
        mat_delta = -mat_delta  # express as user's perspective

    # Eval drop from user's POV (positive = user got worse)
    if side == "white":
        eval_drop_cp = eval_before - eval_after
    else:
        eval_drop_cp = eval_after - eval_before

    return {
        "san": san,
        "piece": piece_name,
        "is_capture": is_capture,
        "is_check": is_check,
        "from_square": chess.square_name(move.from_square),
        "to_square": chess.square_name(move.to_square),
        "phase": phase_of(board_before),
        "eco": eco or "",
        "time_spent": float(time_spent) if time_spent is not None else 0.0,
        "eval_before": int(eval_before) if eval_before is not None else 0,
        "eval_after": int(eval_after) if eval_after is not None else 0,
        "eval_drop_cp": int(eval_drop_cp),
        "hanging_before": hanging_before,
        "hanging_after": hanging_after,
        "hanging_increase": hanging_after - hanging_before,
        "king_attackers_before": king_atk_before,
        "king_attackers_after": king_atk_after,
        "king_attackers_increase": king_atk_after - king_atk_before,
        "material_delta": mat_delta,
    }
