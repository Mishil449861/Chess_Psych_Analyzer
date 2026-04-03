def detect_psychology(delta: int, prev_deltas: list, move_time: float, move_number: int) -> tuple[str, str]:
    """
    Returns (tag, tactics) based on position delta and behavioral signals.
    delta          : centipawn change this full turn (positive = White improved)
    prev_deltas    : list of deltas from recent turns
    move_time      : seconds the user spent on this move
    move_number    : how many full moves have been played
    """
    phase = (
        "Opening"    if move_number < 10  else
        "Middlegame" if move_number < 30  else
        "Endgame"
    )

    # Thresholds scale with phase — opening swings are less alarming
    blunder_threshold  = -200 if phase == "Opening" else -100
    rattled_threshold  =  -60 if phase == "Opening" else  -20

    # Positive swings
    if delta > 100:
        tag     = "Pressing the Advantage"
        tactics = "Forcing"
    elif delta > 40:
        tag     = "Seizing the Initiative"
        tactics = "Active"

    # Negative swings
    elif delta < blunder_threshold:
        tag     = "Critical Miscalculation"
        tactics = "Blunder"
    elif delta < rattled_threshold:
        tag     = "Positional Discomfort"
        tactics = "Passive"

    # Sustained pressure over last 2 turns
    elif len(prev_deltas) >= 2 and all(d < -20 for d in prev_deltas[-2:]):
        tag     = "Loss of Objectivity"
        tactics = "Drifting"

    # Time-based profiling
    elif move_time > 90:
        tag     = "Deep Calculation"
        tactics = "Deliberate"
    elif move_time < 5 and phase != "Opening":
        tag     = "Playing on Intuition"
        tactics = "Impulsive"

    else:
        tag     = "Solid / Prepared"
        tactics = "Balanced"

    return tag, phase
