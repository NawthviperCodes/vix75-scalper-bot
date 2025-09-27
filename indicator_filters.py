def macd_cross(macd_line, signal_line):
    """
    Returns dict with 'buy' and 'sell' keys.
    buy = bullish crossover, sell = bearish crossover.
    """
    if len(macd_line) < 2 or len(signal_line) < 2:
        return {"buy": False, "sell": False}  # not enough data

    return {
        "buy": macd_line[-2] < signal_line[-2] and macd_line[-1] > signal_line[-1],   # bullish
        "sell": macd_line[-2] > signal_line[-2] and macd_line[-1] < signal_line[-1]    # bearish
    }

def rsi_filter(rsi_values, side):
    """
    Returns True if RSI confirms the trade direction.
    For buy: RSI < 30 (oversold) or turning up.
    For sell: RSI > 70 (overbought) or turning down.
    """
    if side == "buy":
        return rsi_values[-1] < 30 or (rsi_values[-2] < rsi_values[-1])
    else:
        return rsi_values[-1] > 70 or (rsi_values[-2] > rsi_values[-1])

def vwap_filter(price, vwap_value, side):
    """
    Confirms if price is in the direction of VWAP.
    Buy: price > VWAP, Sell: price < VWAP
    """
    if side == "buy":
        return price > vwap_value
    else:
        return price < vwap_value
