from decimal import Decimal
import asyncio
from datetime import date, timedelta
import os
from dotenv import load_dotenv
from tastytrade import Session, Account
from tastytrade.instruments import get_option_chain
from tastytrade.order import (
    LimitOrder,
    OrderAction,
    OrderTimeInForce,
    Leg
)

# Load hidden variables from your computer's .env file
load_dotenv()

# ==========================================
# STRATEGY CONFIGURATION
# ==========================================
IS_CERTIFICATION = True  # True = Sandbox / Paper Trading environment
TARGET_DTE = 40
WING_WIDTH = Decimal('5.00')
QUANTITY = Decimal('1')  # 1-contract sizing
TARGET_CREDIT = Decimal('1.50')  # Target net credit limit

async def run_iron_condor_bot():
    print("--- Starting SPY Iron Condor Automation Script ---")

    # 1. Authenticate using your hidden local environment variables
    session = Session(
        os.getenv('TASTY_USERNAME'), 
        os.getenv('TASTY_PASSWORD'), 
        is_certification=IS_CERTIFICATION
    )
    
    accounts = await Account.get(session)
    account = accounts[0]
    print(f"Successfully connected to Sandbox Account: {account.account_number}")

    # 2. Fetch Option Chain for SPY and filter for ~40 DTE
    target_date = date.today() + timedelta(days=TARGET_DTE)
    chain = await get_option_chain(session, 'SPY')
    
    valid_expirations = [exp for exp in chain.keys() if exp >= target_date]
    if not valid_expirations:
        print("Error: No matching expiration dates found.")
        return
    
    selected_expiration = min(valid_expirations)
    print(f"Selected Expiration Date: {selected_expiration}")

    # 3. Construct the 4 Legs for the Iron Condor
    legs = [
        Leg(symbol='SPY_P_STRIKE_1', action=OrderAction.SELL_TO_OPEN, quantity=QUANTITY),
        Leg(symbol='SPY_P_STRIKE_2', action=OrderAction.BUY_TO_OPEN, quantity=QUANTITY),
        Leg(symbol='SPY_P_STRIKE_3', action=OrderAction.SELL_TO_OPEN, quantity=QUANTITY),
        Leg(symbol='SPY_P_STRIKE_4', action=OrderAction.BUY_TO_OPEN, quantity=QUANTITY),
    ]

    # 4. Build the Net Credit Limit Order
    order = LimitOrder(
        legs=legs,
        time_in_force=OrderTimeInForce.GTC,
        price=TARGET_CREDIT
    )

    # 5. Execute a Safe Dry Run in the Sandbox
    print("Submitting order to sandbox for dry-run validation...")
    response = await account.place_order(session, order, dry_run=True)
    print("Dry-Run Validation Result:", response)
    print("--- Script Execution Complete ---")

if __name__ == '__main__':
    asyncio.run(run_iron_condor_bot())
