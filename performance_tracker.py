# === performance_tracker.py (Final Clean Version – trade_log.csv only) ===
import csv
from datetime import datetime, date
import os
from telegram_notifier import send_telegram_message

log_file = "trade_log.csv"

def send_daily_summary():
    today = date.today()
    trades_today = []
    total_profit = 0
    wins = 0
    losses = 0
    trade_details = []

    if not os.path.exists(log_file):
        return

    with open(log_file, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                exit_time = datetime.strptime(row['exit_time'], "%Y-%m-%d %H:%M:%S")
                if exit_time.date() == today:
                    profit = float(row['profit'])
                    result = row['result'].lower()
                    total_profit += profit
                    trades_today.append(row)
                    trade_details.append((
                        row['side'],
                        float(row['entry_price']),
                        float(row['exit_price']),
                        profit,
                        result,
                        row['entry_reason'],
                        row['strategy']
                    ))
                    if result == "win":
                        wins += 1
                    elif result == "loss":
                        losses += 1
            except Exception:
                continue

    if not trades_today:
        send_telegram_message("📊 No trades executed today.")
        return

    total_trades = wins + losses
    win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
    most_common_strategy = max(set([t[6] for t in trade_details]), key=[t[6] for t in trade_details].count)
    most_common_pattern = max(set([t[5] for t in trade_details]), key=[t[5] for t in trade_details].count)

    top_trade = max(trade_details, key=lambda x: x[3])
    worst_trade = min(trade_details, key=lambda x: x[3])

    summary = (
        f"📅 Summary for {today.strftime('%Y-%m-%d')}\n"
        f"Trades: {total_trades} | Wins: {wins} | Losses: {losses} | Win Rate: {win_rate:.1f}%\n"
        f"Total Profit: ${total_profit:.2f}\n\n"
        f"Top Trade ✅\n{top_trade[0].upper()} | Entry: {top_trade[1]:.2f} → Exit: {top_trade[2]:.2f} | "
        f"Profit: ${top_trade[3]:.2f} | Pattern: {top_trade[5]} | Mode: {top_trade[6]}\n\n"
        f"Worst Trade ❌\n{worst_trade[0].upper()} | Entry: {worst_trade[1]:.2f} → Exit: {worst_trade[2]:.2f} | "
        f"Loss: ${worst_trade[3]:.2f} | Pattern: {worst_trade[5]} | Mode: {worst_trade[6]}\n\n"
        f"Most Used Strategy: {most_common_strategy.upper()}\nMost Used Pattern: {most_common_pattern.upper()}"
    )

    send_telegram_message(summary)

    breakdown = "\n🔁 Trades:\n"
    for idx, (side, entry, exit_, profit, result, reason, strategy) in enumerate(trade_details, 1):
        breakdown += (
            f"{idx}. {side.upper()} | {reason} | {strategy} | Entry: {entry:.2f} → Exit: {exit_:.2f} | "
            f"${profit:.2f} | {'✅ WIN' if result == 'win' else '❌ LOSS'}\n"
        )
    send_telegram_message(breakdown)
