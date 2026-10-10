import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import math
from datetime import date, timedelta

# --- SIDEBAR CONTROLS ---
st.sidebar.header("Bull Put Spread Settings (Optimized)")
contracts = st.sidebar.number_input("Number of Contracts", min_value=1, max_value=50, value=1, step=1)

timeframe_option = st.sidebar.selectbox(
    "Backtest Timeframe",
    options=["1 Year", "3 Years", "5 Years"],
    index=1
)

target_dte = st.sidebar.slider("Target DTE (Days to Expiration)", min_value=30, max_value=60, value=45, step=5)
wing_width = st.sidebar.number_input("Spread Width ($)", min_value=1.0, max_value=20.0, value=5.0, step=1.0)

# Optimized Strategy Levers
strike_offset_mult = st.sidebar.slider("Put Strike Offset Multiplier", min_value=1.0, max_value=2.5, value=1.60, step=0.05)
profit_target_pct = st.sidebar.slider("Profit Target (%)", min_value=0.25, max_value=0.90, value=0.50, step=0.05)
stop_loss_mult = st.sidebar.slider("Stop-Loss Multiplier (Risk Multiple)", min_value=1.5, max_value=4.0, value=2.5, step=0.1) # Optimized to 2.5x
min_credit_threshold = st.sidebar.slider("Min Credit to Open ($)", min_value=0.05, max_value=2.00, value=0.18, step=0.05)
manage_at_dte = st.sidebar.slider("Early Management DTE", min_value=10, max_value=30, value=14, step=1)

# Realistic Friction Controls (2-leg spread)
st.sidebar.subheader("Execution Friction")
commission_per_contract = st.sidebar.number_input("Commission ($/contract)", min_value=0.0, max_value=2.0, value=0.65, step=0.05)
slippage_per_leg = st.sidebar.number_input("Slippage ($/share/leg)", min_value=0.0, max_value=0.10, value=0.02, step=0.01)

st.title(f"SPY Bull Put Credit Spread (Optimized) — {target_dte} DTE ({timeframe_option})")

def normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def black_scholes_put_price(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return max(0.0, K - S)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    price = K * math.exp(-r * T) * normal_cdf(-d2) - S * math.exp(-r * T) * normal_cdf(-d1)
    return max(0.01, price)

def simulate_bull_put_spread(num_contracts, timeframe, target_dte, width, offset_m, pt_pct, sl_mult, min_cred, exit_dte, comm, slip):
    today = date.today()
    
    if timeframe == "1 Year":
        eval_start = today - timedelta(days=365)
    elif timeframe == "3 Years":
        eval_start = today - timedelta(days=365 * 3)
    else:
        eval_start = today - timedelta(days=365 * 5)

    download_start = eval_start - timedelta(days=target_dte + 60)
    spy = yf.download("SPY", start=str(download_start), end=str(today), progress=False)

    if spy.empty:
        return pd.DataFrame()

    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    spy["Returns"] = spy["Close"].pct_change()
    spy["Volatility"] = spy["Returns"].rolling(window=30).std() * math.sqrt(252)
    spy["SMA_50"] = spy["Close"].rolling(window=50).mean()

    risk_free_rate = 0.045
    completed_trades = []
    
    active_trade = None
    i = 50
    
    while i < len(spy):
        entry_date = spy.index[i]
        entry_price = float(spy["Close"].iloc[i])
        vol = float(spy["Volatility"].iloc[i])
        sma50 = float(spy["SMA_50"].iloc[i])
        current_date_obj = pd.to_datetime(entry_date).date()

        passes_trend = (entry_price > sma50)

        if active_trade is None:
            if not np.isnan(vol) and current_date_obj >= eval_start and (i < len(spy) - 1) and passes_trend:
                T_entry = target_dte / 365.0
                strike_offset = entry_price * vol * math.sqrt(T_entry) * offset_m
                
                short_put = round(entry_price - strike_offset, 0)
                long_put = short_put - width
                
                sp_val = black_scholes_put_price(entry_price, short_put, T_entry, risk_free_rate, vol)
                lp_val = black_scholes_put_price(entry_price, long_put, T_entry, risk_free_rate, vol)
                
                net_credit = sp_val - lp_val
                
                if net_credit >= min_cred:
                    active_trade = {
                        "Entry Date": entry_date,
                        "Entry Price": entry_price,
                        "Short Put": int(short_put),
                        "Long Put": int(long_put),
                        "initial_credit": net_credit,
                        "days_held": 0
                    }
                    i += 1
                    continue
            i += 1
        else:
            active_trade["days_held"] += 1
            days_held = active_trade["days_held"]
            dte_remaining = target_dte - days_held
            T_remaining = max(0.001, dte_remaining / 365.0)
            
            cur_price = float(spy["Close"].iloc[i])
            
            cur_sp = black_scholes_put_price(cur_price, active_trade["Short Put"], T_remaining, risk_free_rate, vol)
            cur_lp = black_scholes_put_price(cur_price, active_trade["Long Put"], T_remaining, risk_free_rate, vol)
            
            current_spread_value = cur_sp - cur_lp
            total_friction = (comm * 2 * num_contracts) + (slip * 2 * 100 * num_contracts)

            hit_stop = (current_spread_value >= active_trade["initial_credit"] * sl_mult)
            hit_target = (current_spread_value <= active_trade["initial_credit"] * (1.0 - pt_pct))
            hit_management_dte = (dte_remaining <= exit_dte)
            expired = (days_held >= target_dte) or (i == len(spy) - 1)

            if hit_stop:
                pnl = -((active_trade["initial_credit"] * sl_mult - active_trade["initial_credit"]) * 100 * num_contracts) - total_friction
                completed_trades.append({
                    "Entry Date": pd.to_datetime(active_trade["Entry Date"]).strftime("%Y-%m-%d"),
                    "Exit Date": pd.to_datetime(spy.index[i]).strftime("%Y-%m-%d"),
                    "Short / Long Put": f"{active_trade['Short Put']} / {active_trade['Long Put']}",
                    "Outcome": "Stop Loss Hit",
                    "PnL ($)": round(pnl, 2)
                })
                active_trade = None
            elif hit_target:
                pnl = (active_trade["initial_credit"] * pt_pct * 100 * num_contracts) - total_friction
                completed_trades.append({
                    "Entry Date": pd.to_datetime(active_trade["Entry Date"]).strftime("%Y-%m-%d"),
                    "Exit Date": pd.to_datetime(spy.index[i]).strftime("%Y-%m-%d"),
                    "Short / Long Put": f"{active_trade['Short Put']} / {active_trade['Long Put']}",
                    "Outcome": f"{int(pt_pct*100)}% Profit Target",
                    "PnL ($)": round(pnl, 2)
                })
                active_trade = None
            elif hit_management_dte:
                pnl = ((active_trade["initial_credit"] - current_spread_value) * 100 * num_contracts) - total_friction
                completed_trades.append({
                    "Entry Date": pd.to_datetime(active_trade["Entry Date"]).strftime("%Y-%m-%d"),
                    "Exit Date": pd.to_datetime(spy.index[i]).strftime("%Y-%m-%d"),
                    "Short / Long Put": f"{active_trade['Short Put']} / {active_trade['Long Put']}",
                    "Outcome": f"Managed at {exit_dte} DTE",
                    "PnL ($)": round(pnl, 2)
                })
                active_trade = None
            elif expired:
                pnl = (active_trade["initial_credit"] * 100 * num_contracts) - total_friction
                completed_trades.append({
                    "Entry Date": pd.to_datetime(active_trade["Entry Date"]).strftime("%Y-%m-%d"),
                    "Exit Date": pd.to_datetime(spy.index[i]).strftime("%Y-%m-%d"),
                    "Short / Long Put": f"{active_trade['Short Put']} / {active_trade['Long Put']}",
                    "Outcome": "Expired Full Profit",
                    "PnL ($)": round(pnl, 2)
                })
                active_trade = None
            
            i += 1

    return pd.DataFrame(completed_trades)

if st.button("Run Optimized Simulation", type="primary"):
    with st.spinner("Executing optimized backtest..."):
        df_trades = simulate_bull_put_spread(contracts, timeframe_option, target_dte, wing_width, strike_offset_mult, profit_target_pct, stop_loss_mult, min_credit_threshold, manage_at_dte, commission_per_contract, slippage_per_leg)
        
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

            st.subheader(f"Trade Log ({contracts} Contract(s) Sized)")
            st.dataframe(df_trades, use_container_width=True)
        else:
            st.warning("No completed trades generated.")
else:
    st.info("Click **'Run Optimized Simulation'** to see how the wider stop-loss impacts total PnL.")
