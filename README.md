# VIX75 Scalper Bot

An automated trading system for the **Volatility 75 Index** (Deriv) built in Python with MetaTrader 5.  
It monitors market zones, evaluates price-action/indicator confluence, and places trades with risk-based lot sizing.

> **Educational use only — trading involves risk.  
> Do not run on a live account without thorough testing and your own risk controls.**

---

## ✨ Features
- **Dual Strategy Modes**  
  *Trend-Follow (conservative)* or *Aggressive (fast-zone scalping)*.
- **Risk-Based Position Sizing**  
  Default 1 % account-balance risk with broker-min clamp.
- **Telegram Notifications**  
  Trade signals, order confirmations, and daily summaries.
- **MetaTrader 5 Integration**  
  Uses real-time market data and order execution.

---

## 📂 Project Structure

vix75-scalper-bot/
│
├─ src/
│ ├─ main.py # GUI launcher & real-time loop
│ ├─ scalper_strategy_engine.py # Core strategy logic
│ ├─ trade_decision_engine.py # Signal generation
│ ├─ trade_executor.py # Order placement & trailing stops
│ └─ telegram_notifier.py # Telegram alerts (uses env vars)
│
├─ .env.example # Example of required secrets
├─ requirements.txt
└─ README.md


---

## 🛠 Installation
1. **Clone the repo**
   ```bash
   git clone https://github.com/<your-username>/vix75-scalper-bot.git
   cd vix75-scalper-bot


Install dependencies

pip install -r requirements.txt