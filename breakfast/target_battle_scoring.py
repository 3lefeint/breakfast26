"""What a hit is worth in Target Battle, by scoring profile."""

# What a hit on the target is worth by its multiplier. A multiplier that is not listed scores 0.
SCORING = {
    "standard": {1: 1, 2: 2, 3: 3},
    "singles": {1: 1},
    "doubles": {2: 1},
    "triples": {3: 1},
}
