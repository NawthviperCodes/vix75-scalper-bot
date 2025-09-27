import MetaTrader5 as mt5

MAX_SPREAD = 100  # points

def get_current_spread(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return None
    info = mt5.symbol_info(symbol)
    spread = abs(tick.ask - tick.bid) / info.point
    return spread

def is_spread_acceptable(symbol):
    spread = get_current_spread(symbol)
    if spread is None:
        return False
    return spread <= MAX_SPREAD
