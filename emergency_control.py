# === emergency_control.py ===

from datetime import datetime
import MetaTrader5 as mt5

# === Configurable Risk Limits ===
MAX_DAILY_LOSS = -99999999999    # Adjusted: loss allowed before bot stops (realized)
MAX_DRAWDOWN = -999999999999     # Drawdown from peak equity (floating or closed)

# === Session Tracker ===
session_state = {
    "start_equity": None,
    "max_equity": None,
    "last_check_date": datetime.utcnow().date()
}

# Debug flag: Set to True if you want to see risk monitor prints
DEBUG_PRINT = False

def update_equity_stats(current_equity):
    today = datetime.utcnow().date()

    # Reset daily if date has changed
    if today != session_state["last_check_date"]:
        session_state["start_equity"] = current_equity
        session_state["max_equity"] = current_equity
        session_state["last_check_date"] = today

    # Init on startup
    if session_state["start_equity"] is None:
        session_state["start_equity"] = current_equity
    if session_state["max_equity"] is None:
        session_state["max_equity"] = current_equity

    # Track highest equity reached
    if current_equity > session_state["max_equity"]:
        session_state["max_equity"] = current_equity

    daily_profit = current_equity - session_state["start_equity"]
    drawdown = current_equity - session_state["max_equity"]

    return daily_profit, drawdown

def check_emergency_stop(current_equity):
    daily_profit, drawdown = update_equity_stats(current_equity)

    if DEBUG_PRINT:
        print(f"[Risk Monitor] Daily Profit: {daily_profit:.2f} | Drawdown: {drawdown:.2f}")

    if daily_profit < MAX_DAILY_LOSS:
        return "Daily Loss Limit Exceeded"
    if drawdown < MAX_DRAWDOWN:
        return "Max Drawdown Exceeded"
    return None
