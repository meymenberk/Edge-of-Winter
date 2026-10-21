"""Shared, tuneable economy rules for offline and authoritative server play."""
import math


# A session used to grow by 5% every minute (and doubled in twenty minutes).
# A short asymptotic settling curve makes the first visible price adjustment
# after roughly two minutes, then long-term growth continues at only 0.2%/min.
INFLATION_PER_MINUTE = 0.002
EARLY_SETTLING_GROWTH = 0.05
EARLY_SETTLING_MINUTES = 1.2
MAX_INFLATION_MULTIPLIER = 1.35


def inflation_multiplier(elapsed_seconds):
    minutes = max(0.0, float(elapsed_seconds)) / 60.0
    growth = (EARLY_SETTLING_GROWTH * (1.0 - math.exp(-minutes / EARLY_SETTLING_MINUTES))
              + minutes * INFLATION_PER_MINUTE)
    return round(min(MAX_INFLATION_MULTIPLIER, 1.0 + growth), 3)


def inflated_cost(base, multiplier):
    """Apply a slow price curve while making even small scheduled rises visible."""
    multiplier = max(1.0, min(MAX_INFLATION_MULTIPLIER, float(multiplier)))
    return {name: max(1, int(round(amount * multiplier)))
            for name, amount in base.items()}
