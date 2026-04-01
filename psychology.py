def detect_psychology(delta, prev_deltas, move_time, move_number):
    phase = "Opening" if move_number < 10 else "Middlegame" if move_number < 30 else "Endgame"
    
    blunder_threshold = -200 if phase == "Opening" else -100
    rattled_threshold = -60 if phase == "Opening" else -20
    
    if delta > 100: return "Pressing the Advantage"
    if delta > 40: return "Seizing the Initiative"
    
    if delta < blunder_threshold: return "Critical Miscalculation"
    if delta < rattled_threshold: return "Positional Discomfort"
    
    if len(prev_deltas) >= 2 and all(d < -20 for d in prev_deltas[-2:]):
        return "Losing Objectivity"
        
    if move_time > 1.5: return "Deep Calculation"
    if move_time < 0.1 and phase != "Opening": return "Playing on Intuition"
    
    return "Solid / Prepared"