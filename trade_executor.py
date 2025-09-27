import MetaTrader5 as mt5
from telegram_notifier import send_telegram_message

FALLBACK_STOPS_LEVEL = 2000  # in points
TRAILING_TRIGGER = 3000      # trigger trailing after 3000 points profit
TRAILING_STEP = 1000         # trail SL by 1000 points step

def place_order(symbol, order_type, lot, sl_price, tp_price, magic_number):
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        print("[ERROR] Symbol info not found.")
        return None

    # --- Use broker-provided stops_level if possible (safe getattr) ---
    stops_level_raw = getattr(symbol_info, "stops_level", None)
    if stops_level_raw and stops_level_raw > 0:
        stops_level = stops_level_raw * symbol_info.point
    else:
        stops_level = FALLBACK_STOPS_LEVEL * symbol_info.point

    point = symbol_info.point
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print("[ERROR] Failed to get tick.")
        return None

    price = tick.ask if order_type == "buy" else tick.bid
    deviation = 50  # allow more wiggle for VIX75

    # --- Debug info ---
    print(f"[DEBUG] Sending order: type={order_type}, lot={lot}, price={price}, sl={sl_price}, tp={tp_price}")
    print(f"[DEBUG] Broker min lot={symbol_info.volume_min}, max lot={symbol_info.volume_max}, step={symbol_info.volume_step}")
    print(f"[DEBUG] stops_level_raw={stops_level_raw}, computed min SL={stops_level}")

    # Ensure SL/TP not too close
    min_sl_distance = stops_level * 1.2
    if order_type == "buy" and (price - sl_price) < min_sl_distance:
        sl_price = price - min_sl_distance
    elif order_type == "sell" and (sl_price - price) < min_sl_distance:
        sl_price = price + min_sl_distance

    min_tp_distance = stops_level * 1.2
    if order_type == "buy" and (tp_price - price) < min_tp_distance:
        tp_price = price + min_tp_distance
    elif order_type == "sell" and (price - tp_price) < min_tp_distance:
        tp_price = price - min_tp_distance

    print(f"[DEBUG] Final SL distance={abs(price - sl_price):.2f}, TP distance={abs(tp_price - price):.2f}")

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_BUY if order_type == "buy" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": sl_price,
        "tp": tp_price,
        "deviation": deviation,
        "magic": magic_number,
        "comment": "Nawthviper",
        "type_time": mt5.ORDER_TIME_GTC,
        # ↓↓↓ change this line ↓↓↓
        "type_filling": mt5.ORDER_FILLING_FOK,   # <-- use FOK or RETURN
    }
    result = mt5.order_send(request)
    if result is None:
        print("[ERROR] order_send returned None")
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"[ERROR] Order failed. Retcode={result.retcode}, Comment={result.comment}")
        try:
            send_telegram_message(f"❌ Order failed. Retcode={result.retcode}, Comment={result.comment}")
        except:
            pass
        return result

    print(f"[SUCCESS] Order placed! Ticket={result.order}, Price={getattr(result, 'price', price):.2f}")
    try:
        send_telegram_message(f"✅ Order placed! {order_type.upper()} {symbol} @ {price:.2f}")
    except:
        pass
    return result


def place_dynamic_order(symbol, order_type, sl_price, tp_price, magic_number, lot=None):
    account = mt5.account_info()
    if not account:
        print("[ERROR] Failed to get account info.")
        return None

    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        print("[ERROR] Symbol info not found.")
        return None

    # --- Use broker-provided stops_level if possible (safe getattr) ---
    stops_level_raw = getattr(symbol_info, "stops_level", None)
    if stops_level_raw and stops_level_raw > 0:
        stops_level = stops_level_raw * symbol_info.point
    else:
        stops_level = FALLBACK_STOPS_LEVEL * symbol_info.point

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print("[ERROR] Failed to get tick.")
        return None

    price = tick.ask if order_type == "buy" else tick.bid
    sl_distance = abs(price - sl_price)

    # Ensure SL is at least broker min distance
    if sl_distance < stops_level * 1.2:
        sl_distance = stops_level * 1.2
        sl_price = price - sl_distance if order_type == "buy" else price + sl_distance

    balance = account.balance
    contract_size = symbol_info.trade_contract_size

    # --- Dynamic lot sizing if not explicitly passed ---
    if lot is None:
        if balance <= 20:
            risk_percent = 0.005; max_lot = 0.005
        elif balance <= 100:
            risk_percent = 0.01; max_lot = 0.01
        else:
            risk_percent = 0.02; max_lot = 0.1

        risk_amount = balance * risk_percent
        lot = risk_amount / (sl_distance * contract_size)
        lot = min(max_lot, lot)
        lot = max(lot, 0.001)
        lot = round(lot, 3)

    # Debug info
    print(f"[DEBUG] place_dynamic_order → order_type={order_type}, lot={lot}, price={price}, sl={sl_price}, tp={tp_price}")
    print(f"[DEBUG] stops_level_raw={stops_level_raw}, computed min SL={stops_level}")

    return place_order(symbol, order_type, lot, sl_price, tp_price, magic_number)


def trail_sl(symbol, magic, profit_threshold=TRAILING_TRIGGER, step=TRAILING_STEP):
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return

    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        return
    point = symbol_info.point
    stops_level = (getattr(symbol_info, "stops_level", 0) or 500) * point

    for pos in positions:
        if pos.magic != magic:  # remove this line if you want all
            continue

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            continue
        current_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
        direction = 1 if pos.type == mt5.ORDER_TYPE_BUY else -1
        profit_points = (current_price - pos.price_open) * direction / point
        if profit_points <= profit_threshold:
            continue

        new_sl = pos.price_open + (profit_points - step) * direction * point

        # keep minimum broker distance
        if direction == 1 and current_price - new_sl < stops_level:
            new_sl = current_price - stops_level
        elif direction == -1 and new_sl - current_price < stops_level:
            new_sl = current_price + stops_level

        if (direction == 1 and (not pos.sl or new_sl > pos.sl)) or \
           (direction == -1 and (not pos.sl or new_sl < pos.sl)):
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": pos.ticket,
                "sl": round(new_sl, symbol_info.digits),
                "tp": pos.tp,
            }
            result = mt5.order_send(request)
            if not result or result.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"[ERROR] Trail SL failed: {getattr(result,'comment','')}")
            else:
                msg = f"🔐 Trailing SL updated for {symbol} at {new_sl:.2f}"
                print(msg)
                send_telegram_message(msg)
