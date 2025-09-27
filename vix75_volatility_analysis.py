import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# === 1. Load and prepare ===
df = pd.read_csv("September_to_Oct_m1_data.csv", sep="\t")

# Rename columns for convenience
df.columns = [c.strip("<>").lower() for c in df.columns]

# Combine date & time into one datetime index
df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"])
df = df.set_index("datetime")

# === 2. Compute per-minute volatility (High–Low range) ===
df["range"] = df["high"] - df["low"]

# === 3. Aggregate to hourly and daily ===
hourly = df["range"].resample("H").mean()
daily  = df["range"].resample("D").mean()

# Add helper columns
hourly_df = hourly.to_frame("avg_range")
hourly_df["hour"] = hourly_df.index.hour
hourly_df["weekday"] = hourly_df.index.day_name()

# Average by hour of day and day of week
by_hour = hourly_df.groupby("hour")["avg_range"].mean()
by_day  = hourly_df.groupby("weekday")["avg_range"].mean()

# === 4. Visualise ===
by_hour.plot(kind="bar", title="Average Hourly Volatility (High-Low)")
plt.show()

by_day.reindex(
    ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
).plot(kind="bar", title="Average Daily Volatility (High-Low)")
plt.show()

# === 5. Top/Bottom periods ===
print("Top 5 highest-volatility hours:")
print(by_hour.sort_values(ascending=False).head())

print("\nLowest-volatility hours:")
print(by_hour.sort_values().head())

print("\nAverage daily volatility ranking:")
print(by_day.sort_values(ascending=False))
