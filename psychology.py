def detect_psychology(delta, prev_deltas, move_time, move_number):
    phase = "Opening" if move_number < 10 else "Middlegame" if move_number < 30 else "Endgame"
    
    # In the opening, evaluations swing wildly. We need stricter thresholds so it doesn't overreact.
    blunder_threshold = -200 if phase == "Opening" else -100
    rattled_threshold = -60 if phase == "Opening" else -20
    
    # Positive AI Emotions
    if delta > 100: return "Ruthless / Confident"
    if delta > 40: return "Building Pressure"
    
    # Negative AI Emotions 
    if delta < blunder_threshold: return "Shocked / Blunder"
    if delta < rattled_threshold: return "Slightly Rattled"
    
    if len(prev_deltas) >= 2 and all(d < -20 for d in prev_deltas[-2:]):
        return "Frustrated / Tilting"
        
    # Speed based
    if move_time > 1.5: return "Hesitant / Calculating"
    if move_time < 0.1 and phase != "Opening": return "Impulsive / Robotic"
    
    return "Methodical / Cold"