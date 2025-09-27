import MetaTrader5 as mt5

SYMBOL = "Volatility 75 Index"
LOT = 0.001
SLIPPAGE = 5

# Connect to MT5
if not mt5.initialize():
    print("❌ Initialization failed")
    quit()

account_info = mt5.account_info()
if account_info:
    print(f"✅ Connected to account {account_info.login} | Balance: {account_info.balance:.2f}")
else:
    print("❌ Failed to retrieve account info")
    mt5.shutdown()
    quit()

# Load symbol info
symbol_info = mt5.symbol_info(SYMBOL)
if symbol_info is None:
    print(f"❌ Symbol {SYMBOL} not found")
    mt5.shutdown()
    quit()

# Make sure symbol is visible
if not symbol_info.visible:
    if not mt5.symbol_select(SYMBOL, True):
        print(f"❌ Failed to select symbol {SYMBOL}")
        mt5.shutdown()
        quit()

# Print detected filling mode
print(f"ℹ️ Symbol filling mode: {symbol_info.filling_mode}")

# Place BUY order
price = mt5.symbol_info_tick(SYMBOL).bid  # For sell

request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": SYMBOL,
    "volume": LOT,
    "type": mt5.ORDER_TYPE_SELL,
    "price": price,
    "slippage": SLIPPAGE,
    "magic": 10075,
    "comment": "Test SELL VIX75",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_FOK
}

# Send it
result = mt5.order_send(request)
if result.retcode == mt5.TRADE_RETCODE_DONE:
    print(f"✅ SELL order placed! Ticket #{result.order}")
else:
    print(f"❌ Order failed. Retcode: {result.retcode} | Msg: {result.comment}")

mt5.shutdown()
