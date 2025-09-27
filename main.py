# === main.py (Updated with Lot Validation & GUI Fixes) ===
import MetaTrader5 as mt5
import time
import tkinter as tk
from tkinter import messagebox
from scalper_strategy_engine import monitor_and_trade, SYMBOL, TIMEFRAME_ENTRY,send_intro
from emergency_control import check_emergency_stop
from performance_tracker import send_daily_summary
from symbol_info_helper import print_symbol_lot_info
from trade_executor import trail_sl as apply_trailing_stop
from datetime import datetime




STRATEGY_MODE = None
FIXED_LOT_SIZE = None
SUMMARY_SENT = False

def select_strategy_gui():
    global STRATEGY_MODE, FIXED_LOT_SIZE

    def start_bot():
        selected = mode_var.get()
        if selected not in ["trend_follow", "aggressive"]:
            messagebox.showerror("Error", "Please select a strategy mode.")
            return

        STRATEGY_MODE = selected

        try:
            FIXED_LOT_SIZE = float(lot_var.get())
            valid_lots = [0.001, 0.002, 0.005, 0.01]
            if FIXED_LOT_SIZE not in valid_lots:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Invalid lot size selected. Must be 0.001, 0.002, 0.005 or 0.01")
            return

        window.destroy()

    window = tk.Tk()
    window.title("Select Strategy Mode")

    tk.Label(window, text="Which strategy mode do you want?", font=("Arial", 12, "bold")).pack(pady=10)
    mode_var = tk.StringVar()
    tk.Radiobutton(window, text="Trend-Follow (Safe)", variable=mode_var, value="trend_follow").pack(anchor="w", padx=20)
    tk.Radiobutton(window, text="Aggressive (Scalp Beast)", variable=mode_var, value="aggressive").pack(anchor="w", padx=20)

    tk.Label(window, text="Select Lot Size (VIX75):").pack(pady=(10, 0))
    lot_options = ["0.001", "0.002", "0.005", "0.01"]
    lot_var = tk.StringVar(window)
    lot_var.set(lot_options[0])
    tk.OptionMenu(window, lot_var, *lot_options).pack(pady=(0, 10))

    tk.Button(window, text="Start Bot", command=start_bot).pack(pady=20)
    window.mainloop()

def run_bot_realtime():
    global SUMMARY_SENT

    print("Connecting to MetaTrader 5...")
    if not mt5.initialize():
        print("[ERROR] MT5 Initialization Failed!")
        return

    account_info = mt5.account_info()
    if account_info is None:
        print("[ERROR] Failed to get account info.")
    else:
        print(f"Account Number: {account_info.login}")
        print(f"Balance: {account_info.balance:.2f}")
        print(f"Equity: {account_info.equity:.2f}")
        print(f"Leverage: {account_info.leverage}")
        print(f"Server: {account_info.server}\n")
        print_symbol_lot_info(SYMBOL)

    
    print(f"[OK] Bot started in '{STRATEGY_MODE}' mode. Monitoring {SYMBOL} live...\n")
    
    # --- Send Telegram introduction once at startup ---
    try:
        send_intro()
    except Exception as e:
        print(f"[WARN] Failed to send intro: {e}")

    last_candle_time = None

    try:
        while True:
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None:
                print("[ERROR] Could not get tick")
                time.sleep(0.1)
                continue

            rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME_ENTRY, 0, 1)
            if rates is None or len(rates) == 0:
                time.sleep(0.1)
                continue

            current_candle_time = rates[0]['time']
            equity = mt5.account_info().equity

            reason = check_emergency_stop(equity)
            if reason:
                print(f"[EMERGENCY] Bot stopped: {reason}")
                from telegram_notifier import send_telegram_message
                send_telegram_message(f"\u274c Bot stopped: {reason}")
                mt5.shutdown()
                return

            if current_candle_time != last_candle_time:
                last_candle_time = current_candle_time

                try:
                    monitor_and_trade(strategy_mode=STRATEGY_MODE, fixed_lot=FIXED_LOT_SIZE)
                except Exception as e:
                    print(f"[ERROR] Strategy engine failed: {e}")

                apply_trailing_stop(SYMBOL, magic=77775)

                now = datetime.now()
                if 23 <= now.hour < 24 and 58 <= now.minute <= 59 and not SUMMARY_SENT:
                    send_daily_summary()
                    SUMMARY_SENT = True

                if now.hour == 0 and now.minute == 0:
                    SUMMARY_SENT = False

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("Bot stopped by user.")
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    select_strategy_gui()
    run_bot_realtime()
