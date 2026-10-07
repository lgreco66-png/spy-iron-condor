import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import math
from datetime import date, timedelta

# --- SIDEBAR CONTROLS ---
st.sidebar.header("Professional Strategy Settings")
contracts = st.sidebar.number_input("Number of Contracts", min_value=1, max_value=50, value=1, step=1)

timeframe_option = st.sidebar.selectbox(
    "Backtest Timeframe",
    options=["1 Year", "3 Years", "5 Years"],
    index=0
)

target_dte = st.sidebar.slider("Target DTE (Days to Expiration)", min_value=30, max_value=60, value=45, step=5)
wing_width = st.sidebar.number_input("Wing Width ($)", min_value=1.0, max_value=20.0, value=5.0, step=1.0)
stop_loss_mult = st.sidebar.slider("Stop-Loss Multiplier", min_value=1.5, max_value=4.0, value=2.5, step=0.5)

# Friction Settings
commission_per_contract = 0.65 # Standard broker fee per leg
slippage_per_leg = 0.05        # Estimated bid-ask spread slippage per leg

st.title(f"SPY Professional Iron Condor Backtest — {target_dte} DTE ({timeframe_option})")

# --- BUILT-IN MATH NORMAL CDF (Replaces SciPy) ---
def normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

# --- BLACK-SCHOLES PRICING FUNCTION ---
def black_scholes_option_price(S, K, T, r, sigma, option_type="call"):
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K) if option_type == "call" else max(0.0, K - S)
    
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    if option_type == "call":
        price = S * normal_cdf(d1) - K * math.exp(-r * T) * normal_cdf(d2)
    else:
        price = K * math.exp(-r * T) * normal_cdf(-d2) - S * normal_cdf(-d1)
    return max(0.01, price)

def simulate_professional_condor(num_contracts, timeframe, target_dte, width, sl_mult):
    today = date.today()
    
    if timeframe == "1 Year":
        eval_start = today - timedelta(days=365)
    elif timeframe == "3 Years":
        eval_start = today - timedelta(days=365 * 3)
    else:
        eval_start = today - timedelta(days=365 * 5)

    download_start = eval_start - timedelta(days=target_dte + 45)
    spy = yf.download("SPY", start=str(download_start), end=str(today), progress=False)

    if spy.empty:
        return pd.DataFrame()

    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    spy["Returns"] = spy["Close"].pct_change()
    spy["Volatility"] = spy["Returns"].rolling(window=30).std() * np.sqrt(252)

    risk_free_rate = 0.045
    active_trades = []
    completed_trades = []
    
    for i in range(30, len(spy)):
        entry_date = spy.index[i]
        entry_price = float(spy["Close"].iloc[i])
        vol = float(spy["Volatility"].iloc[i])
        current_date_obj = pd.to_datetime(entry_date).date()

        # Update active positions
        still_active = []
        current_price = float(spy["Close"].iloc[i])
        is_last_day = (i == len(spy) - 1)

        for t in active_trades:
            t["days_held"] += 1
            T_remaining = (target_dte - t["days_held"]) / 365.0
            
            cur_short_put_price = black_scholes_option_price(current_price, t["short_put_strike"], max(0.001, T_remaining), risk_free_rate, vol, "put")
            cur_long_put_price = black_scholes_option_price(current_price, t["long_put_strike"], max(0.001, T_remaining), risk_free_rate, vol, "put")
            cur_short_call_price = black_scholes_option_price(current_price, t["short_call_strike"], max(0.001, T_remaining), risk_free_rate, vol, "call")
            cur_long_call_price = black_scholes_option_price(current_price, t["long_call_strike"], max(0.001, T_remaining), risk_free_rate, vol, "call")
            
            current_condor_value = (cur_short_put_price - cur_long_put_price) + (cur_short_call_price - cur_long_call_price)
            
            hit_stop = (current_condor_value >= t["initial_credit"] * sl_mult)
            hit_target = (current_condor_value <= t["initial_credit"] * 0.50)
            expired = (t["days_held"] >= target_dte)

            total_friction = (commission_per_contract * 4 * num_contracts) + (slippage_per_leg * 4 * 100 * num_contracts)

            if hit_stop:
                pnl = -((t["initial_credit"] * sl_mult - t["initial_credit"]) * 100 * num_contracts) - total_friction
                completed_trades.append({**t, "PnL ($)": round(pnl, 2), "Outcome": "Stop-Loss Triggered"})
            elif hit_target:
                pnl = (t["initial_credit"] * 0.50 * 100 * num_contracts) - total_friction
                completed_trades.append({**t, "PnL ($)": round(pnl, 2), "Outcome": "50% Profit Target"})
            elif expired:
                pnl = (t["initial_credit"] * 100 * num_contracts) - total_friction
                completed_trades.append({**t, "PnL ($)": round(pnl, 2), "Outcome": "Expired Full Profit"})
            elif is_last_day:
                continue
            else:
                still_active.append(t)
                
        active_trades = still_active

        # Open new trades
        if not np.isnan(vol) and current_date_obj >= eval_start and (i + target_dte < len(spy)):
            T_entry = target_dte / 365.0
            strike_offset = entry_price * vol * math.sqrt(T_entry) * 1.50
            
            short_put = round(entry_price - strike_offset, 0)
            long_put = short_put - width
            short_call = round(entry_price + strike_offset, 0)
            long_call = short_call + width
            
            sp_val = black_scholes_option_price(entry_price, short_put, T_entry, risk_free_rate, vol, "put")
            lp_val = black_scholes_option_price(entry_price, long_put, T_entry, risk_free_rate, vol, "put")
            sc_val = black_scholes_option_price(entry_price, short_call, T_entry, risk_free_rate, vol, "call")
            lc_val = black_scholes_option_price(entry_price, long_call, T_entry, risk_free_rate, vol, "call")
            
            net_credit = (sp_val - lp_val) + (sc_val - lc_val)
            
            if net_credit > 0.50:
                active_trades.append({
                    "Entry Date": entry_date,
                    "Entry Price": float(entry_price),
                    "Short P/C": f"{int(short_put)} / {int(short_call)}",
                    "initial_credit": net_credit,
                    "short_put_strike": short_put,
                    "long_put_strike": long_put,
                    "short_call_strike": short_call,
                    "long_call_strike": long_call,
                    "days_held": 0
                })

    df = pd.DataFrame(completed_trades)
    if not df.empty and "Entry Date" in df.columns:
        df["Entry Date"] = pd.to_datetime(df["Entry Date"]).dt.strftime("%Y-%m-%d")
    return df

if st.button("Run Professional Simulation", type="primary"):
    with st.spinner("Running Black-Scholes portfolio simulation..."):
        df_trades = simulate_professional_condor(contracts, timeframe_option, target_dte, wing_width, stop_loss_mult)
        
        if not df_trades.empty:
            total_pnl = df_trades["PnL ($)"].sum()
            winning_trades = len(df_trades[df_trades["PnL ($)"] > 0])
            total_trades = len(df_trades)
            win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
            latest_trade_pnl = df_trades.iloc[-1]["PnL ($)"] if not df_trades.empty else 0

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Strategy PnL", f"${total_pnl:,.2f}")
            col2.metric("Latest Trade PnL", f"${latest_trade_pnl:,.2f}")
            col3.metric("Win Rate", f"{win_rate:.1f}%")
            col4.metric("Total Trades", total_trades)

            st.subheader(f"Professional Trade Log ({contracts} Contract(s) Sized)")
            st.dataframe(df_trades, use_container_width=True)
        else:
            st.warning("No completed trades generated for this configuration.")
else:
    st.info("Configure your settings in the sidebar and click **'Run Professional Simulation'**.")
