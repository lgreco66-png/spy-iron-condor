import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf

st.set_page_config(page_title="Iron Condor Backtest", layout="wide")

st.title("SPY Iron Condor Strategy Dashboard")
st.write("Running with wider OTM strikes (1.45x), 50% profit target, and 60-day entry spacing to reduce trade frequency.")
# Function to fetch recent SPY price data dynamically
@st.cache_data(ttl=3600)
def load_live_spy_data():
    spy = yf.Ticker("SPY")
    df = spy.history(period="6mo")
    return df

# Load the data into the app
data = load_live_spy_data()
latest_close = data['Close'].iloc[-1]
latest_date = data.index[-1].strftime('%Y-%m-%d')

st.write(f"**Latest SPY Close Data As Of:** {latest_date} at **${latest_close:.2f}**")
def simulate_iron_condor_backtest():
    spy = yf.download("SPY", start="2020-01-01", end="2026-01-01", progress=False)

    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    spy["Returns"] = spy["Close"].pct_change()
    spy["Volatility"] = spy["Returns"].rolling(window=30).std() * np.sqrt(252)

    dte_target = 40
    wing_width = 5.0
    stop_loss_multiplier = 2.0  

    trades = []
    
    i = 30
    while i < len(spy) - dte_target:
        entry_date = spy.index[i]
        entry_price = spy["Close"].iloc[i]
        vol = spy["Volatility"].iloc[i]

        if np.isnan(vol):
            i += 60
            continue

        # Wider strikes to reduce breach frequency (1.45 multiplier)
        strike_offset = entry_price * vol * np.sqrt(dte_target / 365.0) * 1.45
        short_put = round(entry_price - strike_offset, 0)
        short_call = round(entry_price + strike_offset, 0)

        estimated_credit = round(wing_width * 0.30 * (1 + vol), 2)
        
        pnl = estimated_credit * 100  
        outcome = "Expired Full Profit"

        for j in range(1, dte_target):
            if i + j >= len(spy):
                break
            current_price = spy["Close"].iloc[i + j]

            # Check stop loss
            if current_price <= short_put or current_price >= short_call:
                pnl = -(estimated_credit * stop_loss_multiplier * 100)
                outcome = "Stop-Loss Triggered"
                break
            
            # Early profit target: take 50% profit halfway through cycle if safe
            if j == int(dte_target / 2):
                pnl = estimated_credit * 0.50 * 100
                outcome = "50% Profit Target Reached"
                break

        date_str = entry_date.strftime("%Y-%m-%d") if hasattr(entry_date, 'strftime') else str(entry_date)[:10]

        trades.append({
            "Entry Date": date_str,
            "Entry Price": round(float(entry_price), 2),
            "Short P/C": f"{int(short_put)} / {int(short_call)}",
            "Credit Received": round(float(estimated_credit * 100), 2),
            "PnL ($)": round(float(pnl), 2),
            "Outcome": outcome,
        })
        i += 60  # Spaced out entries every 60 days
        
    return pd.DataFrame(trades)

if st.button("Run Simulation", type="primary"):
    with st.spinner("Running optimized backtest calculation..."):
        df_trades = simulate_iron_condor_backtest()
        
        if not df_trades.empty:
            total_pnl = df_trades["PnL ($)"].sum()
            winning_trades = len(df_trades[df_trades["PnL ($)"] > 0])
            total_trades = len(df_trades)
            win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0

            col1, col2, col3 = st.columns(3)
            col1.metric("Total Strategy PnL", f"${total_pnl:,.2f}")
            col2.metric("Win Rate", f"{win_rate:.1f}%")
            col3.metric("Total Trades", total_trades)

            st.subheader("Trade Log")
            st.dataframe(df_trades, use_container_width=True)
        else:
            st.warning("No trades were generated. Check date ranges.")
else:
    st.info("Click the **'Run Simulation'** button above to generate the backtest results.")
