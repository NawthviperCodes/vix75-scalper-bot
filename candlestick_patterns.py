def is_bullish_pin_bar(open_, high, low, close, threshold=2.0):
    """
    Detects a bullish pin bar (long lower wick, small body at top).
    :param threshold: wick-to-body ratio to qualify as a pin bar
    """
    body = abs(close - open_)
    lower_wick = min(open_, close) - low
    upper_wick = high - max(open_, close)

    return (
        lower_wick > body * threshold and       # Long lower wick
        upper_wick < body and                   # Small upper wick
        close > open_                           # Bullish body
    )


def is_bearish_pin_bar(open_, high, low, close, threshold=2.0):
    """
    Detects a bearish pin bar (long upper wick, small body at bottom).
    """
    body = abs(close - open_)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low

    return (
        upper_wick > body * threshold and       # Long upper wick
        lower_wick < body and                   # Small lower wick
        close < open_                           # Bearish body
    )


def is_bullish_engulfing(o1,h1,l1,c1,o2,h2,l2,c2):
    """
    Strict bullish engulfing: second candle fully engulfs the first (body and ideally wicks).
    """
    return (
        c1 < o1 and                  # first candle bearish
        c2 > o2 and                  # second candle bullish
        o2 < c1 and                  # second opens below first close
        c2 > o1                      # second closes above first open
    )


def is_bearish_engulfing(o1,h1,l1,c1,o2,h2,l2,c2):
    """
    Strict bearish engulfing: second candle fully engulfs the first (body and ideally wicks).
    """
    return (
        c1 > o1 and                  # first candle bullish
        c2 < o2 and                  # second candle bearish
        o2 > c1 and                  # second opens above first close
        c2 < o1                      # second closes below first open
    )


def is_morning_star(c1, c2, c3):
    """
    Bullish 3-candle reversal: down → indecision → strong up
    """
    return (
        c1.close < c1.open and
        c2.close < c2.open and abs(c2.close - c2.open) < abs(c1.open - c1.close) * 0.5 and
        c3.close > c3.open and c3.close > (c1.open + c1.close) / 2
    )


def is_evening_star(c1, c2, c3):
    """
    Bearish 3-candle reversal: up → indecision → strong down
    """
    return (
        c1.close > c1.open and
        c2.close > c2.open and abs(c2.close - c2.open) < abs(c1.close - c1.open) * 0.5 and
        c3.close < c3.open and c3.close < (c1.open + c1.close) / 2
    )


def is_bullish_rectangle(candles):
    """
    Sideways tight-range consolidation after an up move
    """
    candles = list(candles)
    if not candles:
        print("[WARNING] Bullish rectangle skipped: empty candles list")
        return False

    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    return (
        max(highs) - min(lows) < sum([abs(c.open - c.close) for c in candles]) / len(candles) * 2 and
        candles[0].close > candles[-1].close  # Prior uptrend
    )


def is_bearish_rectangle(candles):
    """
    Sideways tight-range consolidation after a down move
    """
    candles = list(candles)
    if not candles:
        print("[WARNING] Bearish rectangle skipped: empty candles list")
        return False

    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    return (
        max(highs) - min(lows) < sum([abs(c.open - c.close) for c in candles]) / len(candles) * 2 and
        candles[0].close < candles[-1].close  # Prior downtrend
    )
