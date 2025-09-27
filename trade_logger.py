import csv
import os
from datetime import datetime

LOG_FILE = "trade_log.csv"
REJECTED_LOG_FILE = "skipped_trades.csv"

HEADER = [
    "timestamp", "strategy", "side", "entry_reason", "zone_price",
    "entry_price", "sl", "tp", "lot_size", "exit_price", "exit_time", "profit", "result"
]

def log_pending_trade(strategy, side, reason, zone, entry, sl, tp, lot):
    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy": strategy,
        "side": side,
        "entry_reason": reason,
        "zone_price": zone,
        "entry_price": entry,
        "sl": sl,
        "tp": tp,
        "lot_size": lot,
        "exit_price": "",
        "exit_time": "",
        "profit": "",
        "result": ""
    }

    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode="a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def update_trade_result(entry_price, side, exit_price, profit):
    rows = []
    updated = False

    with open(LOG_FILE, mode="r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('exit_price') in [None, '', 'nan'] and float(row['entry_price']) == float(entry_price) and row['side'] == side:
                row['exit_price'] = str(exit_price)
                row['exit_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                row['profit'] = str(profit)
                row['result'] = "win" if float(profit) > 0 else "loss"
                updated = True
            rows.append(row)

    if updated:
        with open(LOG_FILE, mode="w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADER)
            writer.writeheader()
            writer.writerows(rows)

def log_skipped_trade(reason, zone_type, zone_price, strategy, trend):
    row = [
        datetime.now().isoformat(),
        strategy,
        zone_type,
        zone_price,
        trend,
        reason
    ]
    file_exists = os.path.isfile(REJECTED_LOG_FILE)
    with open(REJECTED_LOG_FILE, mode="a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "strategy", "zone_type", "zone_price", "trend", "reason"])
        writer.writerow(row)