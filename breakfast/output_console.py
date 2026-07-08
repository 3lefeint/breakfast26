def print_state(state):
    s = state.snapshot()
    current = s.get("current") or {}

    print("\n--- STATE ---")
    print(f"Board: {s['board_status']}")
    print(f"Event: {s['last_event']}")
    print(f"Match: {s['match_started']} | Mode: {s['game_mode']} | Start: {s['points_start']}")
    print(f"Current: #{s['active_player_index']} {s['active_player_name']}")
    print(f"Remaining: {current.get('remaining')}")
    print(
        f"Throws: {current.get('throw1_raw')} | {current.get('throw2_raw')} | {current.get('throw3_raw')}"
    )
    print(
        f"Points: {current.get('throw1_points')} | {current.get('throw2_points')} | {current.get('throw3_points')}"
    )
    print(f"Turn: {current.get('turn_score')}")
    print(f"Bust: {current.get('is_bust')} | Miss: {current.get('last_is_miss')}")
    print(f"Players known: {list(s['players'].keys())}")