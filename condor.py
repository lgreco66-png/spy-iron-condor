import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta

st.title("SPY Iron Condor Live Backtest")

# --- SIDEBAR CONTROLS ---
st.sidebar.header("Strategy Settings")
contracts = st.sidebar.number_input("Number of Contracts", min_value=1, max_value=50, value=5, step=1)

timeframe_option = st.sidebar.selectbox(
    "Backtest Timeframe",
    options=["1 Year", "3 Years", "5 Years", "Max History"],
    index=1 # Defaults to 3 Years
)

trade_frequency = st.sidebar.slider("Trade Frequency (Days apart)", min_value=15, max_value=60, value=30, step=5)

def simulate_iron_condor_backtest(num_contracts, timeframe, freq):
    # Explicitly calculate date bounds so yfinance cannot ignore them
    today = date.today()
    if timeframe == "1 Year":
        start_dt = today - timedelta(days=365)
    elif timeframe == "3 Years":
        start_dt = today - timedelta(days=365 * 3)
    elif timeframe == "5 Years":
        start_dt = today - timedelta(days=365 * 5)
    else:  # Max History
        start_dt = date(2015, 1, 1)

    # Force download with explicit string dates
    spy = yf.download("SPY", start=str(start_dt), end=str(today), progress=False)

    # --- DIAGNOSTIC CHECK ---
    st.write(f"**Debug Info:** Timeframe selected: `{timeframe}` | Rows fetched from Yahoo Finance: `{len(spy)}`")

    if spy.empty:
        return pd.DataFrame()

    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    spy["Returns"] = spy["Close"].pct_change()
    spy["Volatility"] = spy["Returns"].rolling(window=30).std() * np.sqrt(252)

    dte_target = 40
    wing_width = 5.0
    stop_loss_multiplier = 2.5  

    trades = []
    
    i = 30
    while i < len(spy) - dte_target:
        entry_date = spy.index[i]
        entry_price = spy["Close"].iloc[i]
        vol = spy["Volatility"].iloc[i]

        if np.isnan(vol):
            i += freq
            continue

        strike_offset = entry_price * vol * np.sqrt(dte_target / 365.0) * 1.50
        short_put = round(entry_price - strike_offset, 0)
        short_call = round(entry_price + strike_offset, 0)

        estimated_credit = round(wing_width * 0.30 * (1 + vol), 2)
        
        max_risk_per_share = wing_width - estimated_credit
        stop_loss_per_share = min(estimated_credit * stop_loss_multiplier, max_risk_per_share)
        
        pnl = estimated_credit * 100 * num_contracts
        outcome = "Expired Full Profit"

        for j in range(1, dte_target):
            if i + j >= len(spy):
                break
            current_price = spy["Close"].iloc[i + j]

            if current_price <= short_put or current_price >= short_call:
                pnl = -(stop_loss_per_share * 100 * num_contracts)
                outcome = "Stop-Loss Triggered"
                break
            
            if j == int(dte_target / 2):
                pnl = estimated_credit * 0.50 * 100 * num_contracts
                outcome = "50% Profit Target Reached"
                break

        date_str = entry_date.strftime("%Y-%m-%d") if hasattr(entry_date, 'strftime') else str(entry_date)[:10]

        trades.append({
            "Entry Date": date_str,
            "Entry Price": round(float(entry_price), 2),
            "Short P/C": f"{int(short_put)} / {int(short_call)}",
            "Total Credit": round(float(estimated_credit * 100 * num_contracts), 2),
            "PnL ($)": round(float(pnl), 2),
            "Outcome": outcome,
        })
        i += freq  
        
    return pd.DataFrame(trades)

if st.button("Run Simulation", type="primary"):
    with st.spinner("Running dynamic backtest calculation..."):
        df_trades = simulate_iron_condor_backtest(contracts, timeframe_option, trade_frequency)
        
        if not df_trades.empty:
            total_pnl = df_trades["PnL ($)"].sum()
            winning_trades = len(df_trades[df_trades["PnL ($)"] > 0])
            total_trades = len(df_trades)
            win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
            
            latest_trade_pnl = df_trades.iloc[-1]["PnL ($)"]

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Strategy PnL", f"${total_pnl:,.2f}")
            col2.metric("Latest Trade PnL", f"${latest_trade_pnl:,.2f}")
            col3.metric("Win Rate", f"{win_rate:.1f}%")
            col4.metric("Total Trades", total_trades)

            st.subheader(f"Trade Log ({contracts} Contract(s) Sized)")
            st.dataframe(df_trades, use_container_width=True)
        else:
            st.warning("No trades were generated for this timeframe.")
else:
    st.info("Select a timeframe in the sidebar and click **'Run Simulation'**.")
