import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta

# --- SIDEBAR CONTROLS ---
st.sidebar.header("Strategy Settings")
contracts = st.sidebar.number_input("Number of Contracts", min_value=1, max_value=50, value=1, step=1)

timeframe_option = st.sidebar.selectbox(
    "Backtest Timeframe",
    options=["1 Month", "1 Year", "3 Years", "5 Years"],
    index=0 # Defaults to 1 Month
)

# --- DYNAMIC TITLE ---
st.title(f"SPY Iron Condor Portfolio Backtest — {timeframe_option}")

def simulate_iron_condor_backtest(num_contracts, timeframe):
    today = date.today()
    
    if timeframe == "1 Month":
        eval_start = today - timedelta(days=30)
    elif timeframe == "1 Year":
        eval_start = today - timedelta(days=365)
    elif timeframe == "3 Years":
        eval_start = today - timedelta(days=365 * 3)
    else:
        eval_start = today - timedelta(days=365 * 5)

    # Always pull enough history to support indicators and trade lifecycles
    download_start = eval_start - timedelta(days=60)
    spy = yf.download("SPY", start=str(download_start), end=str(today), progress=False)

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
    
    for i in range(30, len(spy)):
        entry_date = spy.index[i]
        entry_price = spy["Close"].iloc[i]
        vol = spy["Volatility"].iloc[i]
        current_date_obj = pd.to_datetime(entry_date).date()

        # Update all currently active positions first
        still_active = []
        current_price = spy["Close"].iloc[i]
        is_last_day = (i == len(spy) - 1)

        for t in active_trades:
            t["days_held"] += 1
            
            short_p, short_c = map(float, t["Short P/C"].split(" / "))
            hit_stop = (current_price <= short_p or current_price >= short_c)
            hit_target = (t["days_held"] == int(dte_target / 2))
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
            elif is_last_day:
                pnl = t["Credit"] * 0.50 * 100 * num_contracts
                completed_trades.append({**t, "PnL ($)": round(pnl, 2), "Outcome": "Still Open (Mark-to-Market)"})
            else:
                still_active.append(t)
                
        active_trades = still_active

        # Open new trades only if within the selected evaluation window
        if not np.isnan(vol) and current_date_obj >= eval_start and not is_last_day:
            strike_offset = entry_price * vol * np.sqrt(dte_target / 365.0) * 1.50
            short_put = round(entry_price - strike_offset, 0)
            short_call = round(entry_price + strike_offset, 0)
            estimated_credit = round(wing_width * 0.30 * (1 + vol), 2)
            
            max_risk_per_share = wing_width - estimated_credit
            stop_loss_per_share = min(estimated_credit * stop_loss_multiplier, max_risk_per_share)
            
            active_trades.append({
                "Entry Date": entry_date,
                "Entry Price": float(entry_price),
                "Short P/C": f"{int(short_put)} / {int(short_call)}",
                "Credit": estimated_credit,
                "stop_loss_per_share": stop_loss_per_share,
                "days_held": 0
            })

    df = pd.DataFrame(completed_trades)
    if not df.empty and "Entry Date" in df.columns:
        df["Entry Date"] = pd.to_datetime(df["Entry Date"]).dt.strftime("%Y-%m-%d")
    return df

if st.button("Run Portfolio Simulation", type="primary"):
    with st.spinner("Running rolling simulation..."):
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
            st.warning("No trades generated for this timeframe.")
else:
    st.info("Select your timeframe in the sidebar and click **'Run Portfolio Simulation'**.")
