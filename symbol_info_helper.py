# === symbol_info_helper.py ===

import MetaTrader5 as mt5

def get_lot_constraints(symbol):
    """
    Returns the min lot, max lot, and lot step size for a symbol.
    Falls back to (0.001, 1.0, 0.001) if info is unavailable.
    """
    info = mt5.symbol_info(symbol)
    if not info:
        return 0.001, 1.0, 0.001  # fallback safe values
    return info.volume_min, info.volume_max, info.volume_step


def print_symbol_lot_info(symbol):
    """
    Prints detailed trading specifications for a symbol.
    """
    info = mt5.symbol_info(symbol)
    if not info:
        print(f"[ERROR] Could not retrieve info for {symbol}")
        return

    print(f"\n=== {symbol} Trading Specs ===")
    print(f"Min Lot Size  : {info.volume_min}")
    print(f"Max Lot Size  : {info.volume_max}")
    print(f"Lot Step Size : {info.volume_step}")
    print(f"Contract Size : {info.trade_contract_size}")
    print(f"Tick Size     : {info.point}")            # safer than trade_tick_size
    print(f"Tick Value    : {info.trade_tick_value}")

    # Hardened: some brokers (like Deriv) don’t expose stops_level
    stops_level = getattr(info, "stops_level", None)
    if stops_level is not None:
        print(f"Stops Level   : {stops_level}")
    else:
        print("Stops Level   : N/A (broker does not report)")
