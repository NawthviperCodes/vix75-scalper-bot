import pandas as pd
from datetime import datetime
from zone_detector import detect_zones
from trade_decision_engine import trade_decision_engine

from candlestick_patterns import (
    is_bullish_pin_bar,
    is_bearish_pin_bar,
    is_bullish_engulfing,
    is_bearish_engulfing
)
from telegram_notifier import send_telegram_message

# === CONFIG ===
H1_FILE = "H1_data.csv"
M1_FILE = "M1_data.csv"
ZONE_LOOKBACK = 100
CHECK_RANGE = 100  # points
SL_BUFFER = 1000
TP_RATIO = 2
LOT_SIZE = 0.002
point = 0.01
account_balance = 100
risk_per_trade = 0.01

# breakout detection parameters
BREAKOUT_CANDLE_FACTOR = 1.5  # candle size > 1.5 x recent average
CONFIRMATION_CANDLES = 2      # number of follow-up candles confirming breakout

# === Stats tracker ===
class BacktestStats:
    def __init__(self, initial_equity):
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.equity = initial_equity
        self.peak_equity = initial_equity
        self.max_drawdown = 0

    def update(self, profit):
        self.total_trades += 1
        if profit > 0:
            self.wins += 1
        else:
            self.losses += 1
        self.equity += profit
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity
        drawdown = self.peak_equity - self.equity
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

    def print_stats(self):
        win_rate = (self.wins / self.total_trades * 100) if self.total_trades else 0
        msg = (
            f"--- Stats Update ---\n"
            f"Total trades: {self.total_trades} | Wins: {self.wins} | Losses: {self.losses} | Win rate: {win_rate:.2f}%\n"
            f"Equity: {self.equity:.2f} | Max Drawdown: {self.max_drawdown:.2f}\n"
            f"--------------------\n"
        )
        print(msg)
        send_telegram_message(msg)

# === Load data ===
h1_df = pd.read_csv(H1_FILE, sep="\t")
h1_df['time'] = pd.to_datetime(h1_df['<DATE>'] + ' ' + h1_df['<TIME>'])
h1_df.rename(columns={
    '<OPEN>':'open',
    '<HIGH>':'high',
    '<LOW>':'low',
    '<CLOSE>':'close'
}, inplace=True)
demand_zones, supply_zones = detect_zones(h1_df, lookback=ZONE_LOOKBACK)

m1_df = pd.read_csv(M1_FILE, sep="\t")
m1_df['time'] = pd.to_datetime(m1_df['<DATE>'] + ' ' + m1_df['<TIME>'])
m1_df.rename(columns={
    '<OPEN>':'open',
    '<HIGH>':'high',
    '<LOW>':'low',
    '<CLOSE>':'close'
}, inplace=True)

# === Initialize ===
stats = BacktestStats(initial_equity=account_balance)
equity_curve = [account_balance]

zone_touch_counts = {}
active_trades = {"buy": False, "sell": False}
open_positions = []

# New: trade history log
trade_history = []

for zone in demand_zones + supply_zones:
    zone_touch_counts[zone['price']] = 0

def check_candle_patterns(candle, prev_candle, is_demand):
    if is_demand:
        return (
            is_bullish_pin_bar(candle.open, candle.high, candle.low, candle.close) or
            is_bullish_engulfing(prev_candle.open, prev_candle.close, candle.open, candle.close)
        )
    else:
        return (
            is_bearish_pin_bar(candle.open, candle.high, candle.low, candle.close) or
            is_bearish_engulfing(prev_candle.open, prev_candle.close, candle.open, candle.close)
        )

# === Backtest loop ===
for i in range(10, len(m1_df)):  # 10 to allow average calc
    candle = m1_df.iloc[i]
    prev_candle = m1_df.iloc[i - 1]
    price = prev_candle.close
    current_time = candle.time

    # manage open positions
    still_open = []
    for pos in open_positions:
        trade_closed = False
        profit = 0
        exit_reason = ""
        if pos['type'] == 'buy':
            if candle.low <= pos['sl']:
                points = pos['sl'] - pos['entry']
                profit = points * pos['lots'] / point
                stats.update(profit)
                active_trades["buy"] = False
                trade_closed = True
                exit_reason = "STOPLOSS HIT"
                send_telegram_message(f"BUY STOPLOSS HIT: {profit:.2f}")
            elif candle.high >= pos['tp']:
                points = pos['tp'] - pos['entry']
                profit = points * pos['lots'] / point
                stats.update(profit)
                active_trades["buy"] = False
                trade_closed = True
                exit_reason = "TAKEPROFIT HIT"
                send_telegram_message(f"BUY TAKEPROFIT HIT: {profit:.2f}")
        elif pos['type'] == 'sell':
            if candle.high >= pos['sl']:
                points = pos['entry'] - pos['sl']
                profit = points * pos['lots'] / point
                stats.update(profit)
                active_trades["sell"] = False
                trade_closed = True
                exit_reason = "STOPLOSS HIT"
                send_telegram_message(f"SELL STOPLOSS HIT: {profit:.2f}")
            elif candle.low <= pos['tp']:
                points = pos['entry'] - pos['tp']
                profit = points * pos['lots'] / point
                stats.update(profit)
                active_trades["sell"] = False
                trade_closed = True
                exit_reason = "TAKEPROFIT HIT"
                send_telegram_message(f"SELL TAKEPROFIT HIT: {profit:.2f}")
        if trade_closed:
            # Log the closed trade
            trade_history.append({
                "entry_time": pos['entry_time'],
                "exit_time": current_time,
                "type": pos['type'],
                "entry_price": pos['entry'],
                "exit_price": pos['sl'] if exit_reason == "STOPLOSS HIT" else pos['tp'],
                "result": "Win" if profit > 0 else "Loss",
                "profit": profit
            })
        else:
            still_open.append(pos)
    open_positions = still_open

    equity_curve.append(stats.equity)

    # === breakout logic helper ===
    def is_valid_breakout(candles, zone_price, direction):
        recent_avg = candles[-10:]['high'].max() - candles[-10:]['low'].min()
        breakout_candle = candles.iloc[-1]
        breakout_size = breakout_candle.high - breakout_candle.low
        if breakout_size > BREAKOUT_CANDLE_FACTOR * recent_avg:
            # check confirmations
            confirms = 0
            for j in range(1, CONFIRMATION_CANDLES+1):
                if direction == "buy":
                    if candles.iloc[-j].close > zone_price:
                        confirms += 1
                else:
                    if candles.iloc[-j].close < zone_price:
                        confirms += 1
            if confirms == CONFIRMATION_CANDLES:
                return True
        return False

    # === demand zone logic ===
    for zone in demand_zones:
        zone_price = zone['price']
        dist = abs(price - zone_price)
        if dist < CHECK_RANGE * point:
            zone_touch_counts[zone_price] += 1
            touches = zone_touch_counts[zone_price]
            if touches == 3:
                if not active_trades["buy"]:
                    if check_candle_patterns(prev_candle, m1_df.iloc[i - 2], True):
                        sl = prev_candle.low - SL_BUFFER * point
                        tp = price + TP_RATIO * (price - sl)
                        open_positions.append({
                            "type": "buy", "entry": price, "sl": sl, "tp": tp, "lots": LOT_SIZE,
                            "entry_time": current_time
                        })
                        active_trades["buy"] = True
                        send_telegram_message(f"BUY after 3rd touch demand zone {zone_price}")
            elif touches >= 4:
                if not active_trades["sell"]:
                    sub_df = m1_df.iloc[i-10:i+1]
                    if is_valid_breakout(sub_df, zone_price, "sell"):
                        sl = zone_price + SL_BUFFER * point
                        tp = price - TP_RATIO * abs(sl - price)
                        open_positions.append({
                            "type": "sell", "entry": price, "sl": sl, "tp": tp, "lots": LOT_SIZE,
                            "entry_time": current_time
                        })
                        active_trades["sell"] = True
                        send_telegram_message(f"REAL BREAKOUT SELL at {zone_price}")
                    else:
                        # treat as false breakout
                        sl = price + SL_BUFFER * point
                        tp = zone_price + TP_RATIO * (price - zone_price)
                        open_positions.append({
                            "type": "buy", "entry": price, "sl": sl, "tp": tp, "lots": LOT_SIZE,
                            "entry_time": current_time
                        })
                        active_trades["buy"] = True
                        send_telegram_message(f"FALSE BREAKOUT BUY at {zone_price}")
                    zone_touch_counts[zone_price] = 0

    # === supply zone logic ===
    for zone in supply_zones:
        zone_price = zone['price']
        dist = abs(price - zone_price)
        if dist < CHECK_RANGE * point:
            zone_touch_counts[zone_price] += 1
            touches = zone_touch_counts[zone_price]
            if touches == 3:
                if not active_trades["sell"]:
                    if check_candle_patterns(prev_candle, m1_df.iloc[i - 2], False):
                        sl = prev_candle.high + SL_BUFFER * point
                        tp = price - TP_RATIO * (sl - price)
                        open_positions.append({
                            "type": "sell", "entry": price, "sl": sl, "tp": tp, "lots": LOT_SIZE,
                            "entry_time": current_time
                        })
                        active_trades["sell"] = True
                        send_telegram_message(f"SELL after 3rd touch supply zone {zone_price}")
            elif touches >= 4:
                if not active_trades["buy"]:
                    sub_df = m1_df.iloc[i-10:i+1]
                    if is_valid_breakout(sub_df, zone_price, "buy"):
                        sl = zone_price - SL_BUFFER * point
                        tp = price + TP_RATIO * abs(price - sl)
                        open_positions.append({
                            "type": "buy", "entry": price, "sl": sl, "tp": tp, "lots": LOT_SIZE,
                            "entry_time": current_time
                        })
                        active_trades["buy"] = True
                        send_telegram_message(f"REAL BREAKOUT BUY at {zone_price}")
                    else:
                        # treat as false breakout
                        sl = price - SL_BUFFER * point
                        tp = zone_price - TP_RATIO * (zone_price - price)
                        open_positions.append({
                            "type": "sell", "entry": price, "sl": sl, "tp": tp, "lots": LOT_SIZE,
                            "entry_time": current_time
                        })
                        active_trades["sell"] = True
                        send_telegram_message(f"FALSE BREAKOUT SELL at {zone_price}")
                    zone_touch_counts[zone_price] = 0

# === Final Stats ===
initial_balance = account_balance
net_profit = stats.equity - initial_balance

final_msg = (
    "\n===== BACKTEST RESULTS =====\n"
    f"Initial Balance: {initial_balance:.2f}\n"
    f"Total Trades: {stats.total_trades}\n"
    f"Wins: {stats.wins}\n"
    f"Losses: {stats.losses}\n"
    f"Win Rate: {(stats.wins / stats.total_trades * 100) if stats.total_trades else 0:.2f}%\n"
    f"Profit Made: {net_profit:.2f}\n"
    f"Final Equity: {stats.equity:.2f}\n"
    f"Max Drawdown: {stats.max_drawdown:.2f}\n"
    "=============================="
)
print(final_msg)
send_telegram_message(final_msg)

# === Print trade history ===
print("\n=== TRADE HISTORY ===")
for t in trade_history:
    print(
        f"Entry: {t['entry_time']} | Exit: {t['exit_time']} | "
        f"Type: {t['type'].upper()} | Entry Price: {t['entry_price']:.5f} | "
        f"Exit Price: {t['exit_price']:.5f} | Result: {t['result']} | Profit: {t['profit']:.2f}"
    )
