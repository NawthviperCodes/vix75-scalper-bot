import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib.pyplot as plt
from ta.trend import MACD
from ta.momentum import RSIIndicator
from ta.volume import VolumeWeightedAveragePrice
from ta.volatility import AverageTrueRange

import trade_decision_engine

class BacktestEngine:
    def __init__(self, h1_data_path, m1_data_path):
        self.h1_data = self.load_data(h1_data_path, is_h1=True)
        self.m1_data = self.load_data(m1_data_path, is_h1=False)
        self.symbol = "Volatility 75 Index"
        self.point = 0.01  # Assuming 1 point = 0.01
        self.initial_balance = 10000
        self.balance = self.initial_balance
        self.equity = []
        self.trades = []
        self.active_trades = {}
        self.zone_touch_counts = {}
        self.SL_BUFFER = 15000
        self.TP_RATIO = 2
        self.CHECK_RANGE = 30000
        self.MIN_LOT = 0.001
        self.MAGIC = 77775
        self.commission = 0.0002  # 0.02% commission per trade
        
    def load_data(self, file_path, is_h1):
        """Load and preprocess historical data with the specific format"""
        # Read CSV file with proper separator (tab in this case)
        df = pd.read_csv(file_path, sep='\t')
        
        # Clean column names by removing angle brackets
        df.columns = [col.replace('<', '').replace('>', '') for col in df.columns]
        
        # Create proper datetime column from DATE and TIME columns
        df['datetime'] = pd.to_datetime(df['DATE'] + ' ' + df['TIME'])
        
        # Ensure numeric columns are properly formatted
        numeric_cols = ['OPEN', 'HIGH', 'LOW', 'CLOSE', 'TICKVOL', 'VOL', 'SPREAD']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Drop any rows with missing essential data
        df = df.dropna(subset=['OPEN', 'HIGH', 'LOW', 'CLOSE', 'datetime'])
        
        # Sort by datetime and reset index
        df = df.sort_values('datetime').reset_index(drop=True)
        
        # Calculate typical price for VWAP
        df['typical_price'] = (df['HIGH'] + df['LOW'] + df['CLOSE']) / 3
        
        # Standardize column names to lowercase
        df.columns = [col.lower() for col in df.columns]
        
        return df
    
    def calculate_indicators(self, df):
        """Calculate technical indicators for the given dataframe"""
        if len(df) < 35:
            return None, None, None, None, None
            
        try:
            macd_calc = MACD(close=df['close'])
            macd_line = macd_calc.macd().dropna().values
            macd_signal = macd_calc.macd_signal().dropna().values
            rsi_values = RSIIndicator(close=df['close']).rsi().dropna().values
            vwap_value = VolumeWeightedAveragePrice(
                high=df['high'], low=df['low'], close=df['close'], volume=df['vol']
            ).vwap.iloc[-1]
            atr = AverageTrueRange(high=df['high'], low=df['low'], close=df['close']).average_true_range().iloc[-1]
            return macd_line, macd_signal, rsi_values, vwap_value, atr
        except Exception as e:
            print(f"Indicator calculation error: {e}")
            return None, None, None, None, None
    
    def detect_zones(self, df):
        """Mock zone detection - replace with your actual implementation"""
        # This is a placeholder - you should replace with your actual zone detection logic
        demand_zones = [{'price': df['low'].min(), 'time': df['datetime'].iloc[0]}]
        supply_zones = [{'price': df['high'].max(), 'time': df['datetime'].iloc[0]}]
        return demand_zones, supply_zones
    
    def detect_fast_zones(self, df):
        """Mock fast zone detection - replace with your actual implementation"""
        # This is a placeholder - you should replace with your actual fast zone detection logic
        fast_demand = [{'price': df['low'].min() + 10, 'time': df['datetime'].iloc[0], 'type': 'fast'}]
        fast_supply = [{'price': df['high'].max() - 10, 'time': df['datetime'].iloc[0], 'type': 'fast'}]
        return fast_demand, fast_supply
    
    def calculate_h1_trend(self, h1_df):
        """Calculate the H1 trend based on SMA50"""
        if len(h1_df) < 51:
            return None
            
        h1_df['SMA50'] = h1_df['close'].rolling(50).mean()
        last = h1_df['close'].iloc[-1]
        sma = h1_df['SMA50'].iloc[-1]
        
        if last > sma:
            return "uptrend"
        elif last < sma:
            return "downtrend"
        else:
            return "sideways"
    
    def run_backtest(self):
        """Main backtest execution loop"""
        print("Starting backtest...")
        
        # Process H1 data first to identify zones
        h1_zones = {}
        for i in range(len(self.h1_data)):
            current_h1 = self.h1_data.iloc[i]
            h1_window = self.h1_data.iloc[max(0, i-100):i+1]
            
            demand_zones, supply_zones = self.detect_zones(h1_window)
            fast_demand, fast_supply = self.detect_fast_zones(h1_window)
            
            h1_zones[current_h1['datetime']] = {
                'demand': demand_zones,
                'supply': supply_zones,
                'fast_demand': fast_demand,
                'fast_supply': fast_supply
            }
        
        # Process M1 data for trading
        for i in range(len(self.m1_data)):
            if i < 35:  # Skip initial candles that don't have enough data for indicators
                continue
                
            current_m1 = self.m1_data.iloc[i]
            m1_window = self.m1_data.iloc[max(0, i-100):i+1]
            
            # Find corresponding H1 data
            h1_time = current_m1['datetime'].floor('H')
            if h1_time not in h1_zones:
                continue
                
            zones = h1_zones[h1_time]
            trend = self.calculate_h1_trend(self.h1_data[self.h1_data['datetime'] <= h1_time])
            
            if not trend:
                continue
                
            # Calculate indicators
            macd, macd_signal, rsi, vwap, atr = self.calculate_indicators(m1_window)
            
            # Get last 3 candles for decision making
            last3_candles = m1_window.iloc[-3:] if len(m1_window) >= 3 else None
            
            if last3_candles is None:
                continue
                
            # Run trade decision engine
            signals = trade_decision_engine(
                symbol=self.symbol,
                point=self.point,
                current_price=current_m1['close'],
                trend=trend,
                demand_zones=zones['demand'],
                supply_zones=zones['supply'],
                last3_candles=last3_candles,
                active_trades=self.active_trades,
                zone_touch_counts=self.zone_touch_counts,
                SL_BUFFER=self.SL_BUFFER,
                TP_RATIO=self.TP_RATIO,
                CHECK_RANGE=self.CHECK_RANGE,
                LOT_SIZE=self.MIN_LOT,
                MAGIC=self.MAGIC,
                strategy_mode="trend_follow",
                macd=macd,
                macd_signal=macd_signal,
                rsi=rsi,
                vwap=vwap,
                atr=atr
            )
            
            # Process signals
            for signal in signals:
                self.execute_trade(signal, current_m1)
            
            # Check for closed trades
            self.check_closed_trades(current_m1)
            
            # Update equity curve
            self.equity.append({
                'datetime': current_m1['datetime'],
                'balance': self.balance,
                'open_trades': len(self.active_trades)
            })
        
        print("Backtest completed")
        self.generate_report()
    
    def execute_trade(self, signal, current_candle):
        """Execute a trade based on the signal"""
        entry_price = signal['entry']
        sl_price = signal['sl']
        tp_price = signal['tp']
        lot_size = signal['lot']
        side = signal['side']
        
        # Calculate position size based on risk (1% of balance)
        risk_amount = self.balance * 0.01
        price_diff = abs(entry_price - sl_price)
        lot_size = max(self.MIN_LOT, risk_amount / (price_diff * 100))  # Assuming 1 lot = 100 units
        
        # Create trade record
        trade_id = len(self.trades) + 1
        trade = {
            'id': trade_id,
            'entry_time': current_candle['datetime'],
            'side': side,
            'entry_price': entry_price,
            'sl_price': sl_price,
            'tp_price': tp_price,
            'lot_size': lot_size,
            'status': 'open',
            'exit_time': None,
            'exit_price': None,
            'profit': None
        }
        
        self.trades.append(trade)
        self.active_trades[trade_id] = trade
        
        print(f"{current_candle['datetime']} - {side.upper()} order executed at {entry_price}")
    
    def check_closed_trades(self, current_candle):
        """Check if any open trades should be closed"""
        current_price = current_candle['close']
        high_price = current_candle['high']
        low_price = current_candle['low']
        
        for trade_id, trade in list(self.active_trades.items()):
            if trade['side'] == 'buy':
                # Check for TP hit
                if high_price >= trade['tp_price']:
                    self.close_trade(trade_id, trade['tp_price'], current_candle['datetime'], 'tp')
                # Check for SL hit
                elif low_price <= trade['sl_price']:
                    self.close_trade(trade_id, trade['sl_price'], current_candle['datetime'], 'sl')
            else:  # sell
                # Check for TP hit
                if low_price <= trade['tp_price']:
                    self.close_trade(trade_id, trade['tp_price'], current_candle['datetime'], 'tp')
                # Check for SL hit
                elif high_price >= trade['sl_price']:
                    self.close_trade(trade_id, trade['sl_price'], current_candle['datetime'], 'sl')
    
    def close_trade(self, trade_id, exit_price, exit_time, reason):
        """Close a trade and calculate P&L"""
        if trade_id not in self.active_trades:
            return
            
        trade = self.active_trades[trade_id]
        price_diff = exit_price - trade['entry_price'] if trade['side'] == 'buy' else trade['entry_price'] - exit_price
        profit = price_diff * trade['lot_size'] * 100  # Assuming 1 lot = 100 units
        
        # Apply commission
        commission = (trade['entry_price'] * trade['lot_size'] * 100 * self.commission) + \
                    (exit_price * trade['lot_size'] * 100 * self.commission)
        profit -= commission
        
        # Update trade record
        trade['exit_time'] = exit_time
        trade['exit_price'] = exit_price
        trade['profit'] = profit
        trade['status'] = 'closed'
        trade['close_reason'] = reason
        
        # Update balance
        self.balance += profit
        
        # Remove from active trades
        del self.active_trades[trade_id]
        
        print(f"{exit_time} - {trade['side'].upper()} order closed at {exit_price} ({reason}), P&L: {profit:.2f}")
    
    def generate_report(self):
        """Generate performance report and charts"""
        if not self.trades:
            print("No trades were executed during the backtest period")
            return
            
        # Convert trades to DataFrame
        trades_df = pd.DataFrame(self.trades)
        
        # Convert equity to DataFrame
        equity_df = pd.DataFrame(self.equity)
        equity_df.set_index('datetime', inplace=True)
        
        # Calculate performance metrics
        total_trades = len(trades_df)
        winning_trades = len(trades_df[trades_df['profit'] > 0])
        losing_trades = len(trades_df[trades_df['profit'] < 0])
        win_rate = winning_trades / total_trades * 100
        avg_win = trades_df[trades_df['profit'] > 0]['profit'].mean()
        avg_loss = trades_df[trades_df['profit'] < 0]['profit'].mean()
        profit_factor = abs(avg_win * winning_trades) / abs(avg_loss * losing_trades) if losing_trades > 0 else np.inf
        max_drawdown = (equity_df['balance'].max() - equity_df['balance'].min()) / equity_df['balance'].max() * 100
        final_balance = self.balance
        roi = (final_balance - self.initial_balance) / self.initial_balance * 100
        
        # Print summary
        print("\n=== Backtest Results ===")
        print(f"Initial Balance: ${self.initial_balance:.2f}")
        print(f"Final Balance: ${final_balance:.2f}")
        print(f"ROI: {roi:.2f}%")
        print(f"Total Trades: {total_trades}")
        print(f"Winning Trades: {winning_trades} ({win_rate:.2f}%)")
        print(f"Losing Trades: {losing_trades}")
        print(f"Average Win: ${avg_win:.2f}")
        print(f"Average Loss: ${avg_loss:.2f}")
        print(f"Profit Factor: {profit_factor:.2f}")
        print(f"Max Drawdown: {max_drawdown:.2f}%")
        
        # Plot equity curve
        plt.figure(figsize=(12, 6))
        plt.plot(equity_df.index, equity_df['balance'], label='Equity Curve')
        plt.title('Equity Curve')
        plt.xlabel('Date')
        plt.ylabel('Balance')
        plt.grid(True)
        plt.legend()
        plt.show()
        
        # Plot trades histogram
        plt.figure(figsize=(8, 5))
        plt.hist(trades_df['profit'], bins=30, color='skyblue', edgecolor='black')
        plt.title('Profit Distribution')
        plt.xlabel('Profit')
        plt.ylabel('Frequency')
        plt.grid(True)
        plt.show()
        
        # Save results to CSV
        trades_df.to_csv('backtest_trades.csv', index=False)
        equity_df.to_csv('backtest_equity.csv')

if __name__ == "__main__":
    # Initialize and run backtest
    backtester = BacktestEngine(
        h1_data_path="H1_data.csv",
        m1_data_path="M1_data.csv"
    )
    backtester.run_backtest()