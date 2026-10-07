import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta

st.title("SPY Iron Condor Daily Portfolio Backtest")

# --- SIDEBAR CONTROLS ---
st.sidebar.header("Strategy Settings")
contracts = st.sidebar.number_input("Number of Contracts", min_value=1, max_value=50, value=1, step=1)

timeframe_option = st.sidebar.selectbox(
    "Backtest Timeframe",
    options=["1 Year", "3 Years", "5 Years"],
    index=0 # Defaults to 1 Year
)

def simulate_iron_condor_backtest(num_contracts, timeframe):
    today = date.today()
    if timeframe == "1 Year":
        start_dt = today - timedelta(days=365)
    elif timeframe == "3 Years":
        start_dt = today - timedelta(days=365 * 3)
    else:
        start_dt = today - timedelta(days=365 * 5)

    spy = yf.download("SPY", start=str(start_dt), end=str(today), progress=False)

    if spy.empty:
        return pd.DataFrame()

    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    spy["Returns"] = spy["Close"].pct_change()
    spy["Volatility"] = spy["Returns"].rolling(window=30).std() * np.sqrt(252)

    dte_target = 40
    wing_width = 5.0
    stop_loss_multiplier = 2.5  

    active_trades = []
    completed_trades = []
    
    # Loop day by day to open a trade every single session
    for i in range(30, len(spy) - 1):
        entry_date = spy.index[i]
        entry_price = spy["Close"].iloc[i]
        vol = spy["Volatility"].iloc[i]

        if not np.isnan(vol):
            strike_offset = entry_price * vol * np.sqrt(dte_target / 365.0) * 1.50
            short_put = round(entry_price - strike_offset, 0)
            short_call = round(entry_price + strike_offset, 0)
            estimated_credit = round(wing_width * 0.30 * (1 + vol), 2)
            
            max_risk_per_share = wing_width - estimated_credit
            stop_loss_per_share = min(estimated_credit * stop_loss_multiplier, max_risk_per_share)
            
            # Open new trade
            active_trades.append({
                "Entry Date": entry_date,
                "Entry Price": float(entry_price),
                "Short P/C": f"{int(short_put)} / {int(short_call)}",
                "Credit": estimated_credit,
                "stop_loss_per_share": stop_loss_per_share,
                "days_held": 0
            })

        # Update all currently active positions for today's price action
        still_active = []
        current_price = spy["Close"].iloc[i]

        for t in active_trades:
            t["days_held"] += 1
            
            # Check exit conditions
            short_p, short_c = map(float, t["Short P/C"].split(" / "))
            hit_stop = (current_price <= short_p or current_price >= short_c)
            hit_target = (t["days_held"] == int(dte_target / 2)) # 50% profit target
            expired = (t["days_held"] >= dte_target)

            if hit_stop:
                pnl = -(t["stop_loss_per_share"] * 100 * num_contracts)
                completed_trades.append({**t, "PnL ($)": round(pnl, 2), "Outcome": "Stop-Loss Triggered"})
            elif hit_target:
                pnl = t["Credit"] * 0.50 * 100 * num_contracts
                completed_trades.append({**t, "PnL ($)": round(pnl, 2), "Outcome": "50% Profit Target"})
            elif expired:
                pnl = t["Credit"] * 100 * num_contracts
                completed_trades.append({**t, "PnL ($)": round(pnl, 2), "Outcome": "Expired Full Profit"})
            else:
                still_active.append(t)
                
        active_trades = stillness = still_active

    # Convert results to DataFrame
    df = pd.DataFrame(completed_trades)
    if not df.empty and "Entry Date" in df.columns:
        df["Entry Date"] = pd.to_datetime(df["Entry Date"]).dt.strftime("%Y-%m-%d")
    return df

if st.button("Run Daily Portfolio Simulation", type="primary"):
    with st.spinner("Running daily rolling simulation..."):
        df_trades = simulate_iron_condor_backtest(contracts, timeframe_option)
        
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
            st.warning("No trades generated.")
else:
    st.info("Click **'Run Daily Portfolio Simulation'** to execute daily trade entries.")
