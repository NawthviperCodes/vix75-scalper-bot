import MetaTrader5 as mt5
from symbol_info_helper import print_symbol_lot_info

symbol = "Volatility 75 Index"

# Initialize MT5
if not mt5.initialize():
    print("[ERROR] Failed to initialize MetaTrader 5.")
    quit()

# Print lot constraints
print_symbol_lot_info(symbol)

# Shutdown MT5
mt5.shutdown()
