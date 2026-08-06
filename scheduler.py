import logging
import asyncio
import json
from datetime import datetime, date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import yfinance as yf

from agent import FinancialAgent
import database

logger = logging.getLogger(__name__)

_bot_instance = None
scheduler = AsyncIOScheduler()

def _get_ticker(symbol: str) -> yf.Ticker:
    import requests
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    return yf.Ticker(symbol, session=session)

def _fetch_price_with_fallbacks(ticker: str):
    """
    Fetch current stock price and previous close using three fallback layers:
    1. Direct lightweight Yahoo Chart API request
    2. yfinance history query with Chrome session headers
    3. DuckDuckGo search + Regex parser
    """
    ticker = ticker.upper().strip()
    
    # Layer 1: Direct Yahoo Chart API
    try:
        import requests
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        r = requests.get(url, params={"range": "2d", "interval": "1d"}, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            result = data.get('chart', {}).get('result', [])
            if result:
                meta = result[0].get('meta', {})
                current_price = meta.get('regularMarketPrice')
                prev_close = meta.get('chartPreviousClose')
                if current_price is not None:
                    return float(current_price), float(prev_close) if prev_close is not None else float(current_price)
    except Exception as e:
        logger.debug(f"Direct Yahoo chart API failed for {ticker}: {e}")

    # Layer 2: yfinance history query
    try:
        t_obj = _get_ticker(ticker)
        hist = t_obj.history(period="2d")
        if not hist.empty:
            current_price = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else current_price
            return float(current_price), float(prev_close)
    except Exception as e:
        logger.debug(f"yfinance history query failed for {ticker}: {e}")

    # Layer 3: DuckDuckGo search + regex extraction
    try:
        from tools.web_tools import search_web
        query = f"{ticker} stock price Google Finance today"
        search_res = search_web(query, max_results=3)
        if "Ratelimit" not in search_res:
            import re
            numbers = re.findall(r'(?:\$)?\d+(?:\.\d+)?', search_res)
            valid_prices = []
            for n in numbers:
                clean_n = n.replace('$', '')
                try:
                    val = float(clean_n)
                    if 0.5 <= val <= 150000.0:
                        valid_prices.append(val)
                except ValueError:
                    continue
            if valid_prices:
                current_price = valid_prices[0]
                prev_close = valid_prices[1] if len(valid_prices) > 1 else current_price
                logger.info(f"Extracted price {current_price} from search results for {ticker}")
                return current_price, prev_close
    except Exception as e:
        logger.error(f"Web search price extraction failed for {ticker}: {e}")

    return None, None

# Keeps track of alerts sent today to prevent spamming the user multiple times for the same ticker
# Format: { date_str: { (chat_id, ticker) } }
_sent_alerts_log = {}

async def send_daily_briefing(chat_id: int, bot):
    """
    Generate and send the daily morning briefing.
    """
    logger.info(f"Triggering scheduled daily briefing for user {chat_id}...")
    try:
        # Create agent instance
        agent = FinancialAgent(chat_id)
        
        # Request the agent to generate a briefing
        prompt = (
            "Generate my morning market briefing now. "
            "Please check the performance of major indices and look up news and prices for the companies on my watchlist. "
            "Explain what's moving and why. Keep it dense, bulleted, and ready for quick mobile reading."
        )
        
        briefing_text = agent.chat(prompt)
        await bot.send_message(chat_id=chat_id, text=briefing_text, parse_mode="Markdown")
        logger.info(f"Daily briefing sent to user {chat_id}.")
    except Exception as e:
        logger.error(f"Failed to send daily briefing to {chat_id}: {e}")

async def send_evening_briefing(chat_id: int, bot):
    """
    Generate and send the daily evening market summary.
    """
    logger.info(f"Triggering scheduled daily evening briefing for user {chat_id}...")
    try:
        agent = FinancialAgent(chat_id)
        prompt = (
            "Generate my evening market summary now. "
            "Please check how major indices closed today, summarize any major stock price movements or news on my watchlist, "
            "and highlight key earnings reports or filings released after market close. "
            "Keep it dense, bulleted, and ready for quick mobile reading."
        )
        briefing_text = agent.chat(prompt)
        await bot.send_message(chat_id=chat_id, text=briefing_text, parse_mode="Markdown")
        logger.info(f"Evening briefing sent to user {chat_id}.")
    except Exception as e:
        logger.error(f"Failed to send evening briefing to {chat_id}: {e}")

async def check_watchlist_anomalies(bot):
    """
    Scan watchlists for major movements (>5% shift) and explain the drivers.
    """
    logger.info("Scanning watchlists for price anomalies...")
    today_str = date.today().isoformat()
    if today_str not in _sent_alerts_log:
        _sent_alerts_log.clear() # Reset previous days
        _sent_alerts_log[today_str] = set()
        
    conn = database.get_db_connection()
    users = conn.execute("SELECT chat_id, preferences FROM users WHERE onboarding_status = 'completed'").fetchall()
    conn.close()
    
    if not users:
        return
        
    # Map users to their watchlists
    user_watchlists = {}
    all_tickers = set()
    for row in users:
        chat_id = row['chat_id']
        try:
            prefs = json.loads(row['preferences']) if row['preferences'] else {}
        except Exception:
            prefs = {}
        watchlist = prefs.get('watchlist', [])
        if watchlist:
            user_watchlists[chat_id] = watchlist
            all_tickers.update(watchlist)
            
    if not all_tickers:
        return
        
    # Check current day performance for each ticker
    for ticker in all_tickers:
        try:
            prices = _fetch_price_with_fallbacks(ticker)
            if not prices or prices[0] is None:
                continue
                
            current_price, prev_close = prices
                
            pct_change = ((current_price - prev_close) / prev_close) * 100
            
            # If the change is significant (> 5.0% movement)
            if abs(pct_change) >= 5.0:
                logger.info(f"Anomaly detected for {ticker}: {pct_change:+.2f}%")
                
                # Identify which users follow this ticker and haven't been alerted today
                for chat_id, watchlist in user_watchlists.items():
                    if ticker in watchlist and (chat_id, ticker) not in _sent_alerts_log[today_str]:
                        # Generate alert using the agent to search for the driver
                        agent = FinancialAgent(chat_id)
                        direction = "up" if pct_change > 0 else "down"
                        alert_prompt = (
                            f"ALERT: {ticker} is {direction} {pct_change:+.2f}% today (trading at {current_price:.2f}). "
                            f"Search the web or financial news for any major announcements, earnings, or events today, "
                            f"and write a very brief 2-sentence explanation of what is causing this move."
                        )
                        
                        explanation = agent.chat(alert_prompt)
                        
                        # Add header to explanation
                        full_message = f"🚨 **Watchlist Alert: {ticker}**\n{explanation}"
                        
                        await bot.send_message(chat_id=chat_id, text=full_message, parse_mode="Markdown")
                        _sent_alerts_log[today_str].add((chat_id, ticker))
                        logger.info(f"Sent anomaly alert for {ticker} to {chat_id}")
                        
        except Exception as e:
            logger.error(f"Error checking anomaly for ticker {ticker}: {e}")

async def check_custom_alerts(bot):
    """
    Scan active user-configured price/percentage alerts and trigger notifications.
    """
    logger.info("Running scheduled user alerts check...")
    try:
        alerts = database.get_active_alerts()
        if not alerts:
            return
            
        # Group alerts by ticker to reduce yfinance requests
        ticker_alerts = {}
        for a in alerts:
            t = a['ticker']
            ticker_alerts.setdefault(t, []).append(a)
            
        for ticker, t_alerts in ticker_alerts.items():
            try:
                prices = _fetch_price_with_fallbacks(ticker)
                if not prices or prices[0] is None:
                    logger.warning(f"No price found for {ticker}")
                    continue
                    
                current_price, prev_close = prices
                
                for a in t_alerts:
                    alert_id = a['id']
                    chat_id = a['chat_id']
                    alert_type = a['alert_type']
                    target_value = a['target_value']
                    condition = a['condition']
                    
                    trigger_fired = False
                    reason = ""
                    
                    if alert_type == 'price':
                        if condition == 'above' and current_price >= target_value:
                            trigger_fired = True
                            reason = f"crossed above target price of ${target_value:.2f} (current: ${current_price:.2f})"
                        elif condition == 'below' and current_price <= target_value:
                            trigger_fired = True
                            reason = f"dropped below target price of ${target_value:.2f} (current: ${current_price:.2f})"
                    elif alert_type == 'percentage' and prev_close:
                        change_pct = ((current_price - prev_close) / prev_close) * 100.0
                        if condition == 'above' and change_pct >= target_value:
                            trigger_fired = True
                            reason = f"gained {change_pct:.2f}% (target: >= {target_value:.2f}%) today (current: ${current_price:.2f})"
                        elif condition == 'below' and change_pct <= target_value:
                            normalized_target = target_value if target_value < 0 else -target_value
                            if change_pct <= normalized_target:
                                trigger_fired = True
                                reason = f"lost {change_pct:.2f}% (target: <= {normalized_target:.2f}%) today (current: ${current_price:.2f})"
                        elif condition == 'movement':
                            if abs(change_pct) >= abs(target_value):
                                dir_str = "gained" if change_pct > 0 else "lost"
                                trigger_fired = True
                                reason = f"moved {dir_str} {change_pct:.2f}% (target: {target_value:.2f}% change) today (current: ${current_price:.2f})"
                                
                    if trigger_fired:
                        msg = f"🔔 **Custom Alert Triggered!**\n\n**{ticker}** {reason}."
                        if bot:
                            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                        logger.info(f"Fired custom alert {alert_id} for user {chat_id}: {msg}")
                        database.mark_alert_triggered(alert_id)
            except Exception as e:
                logger.error(f"Error checking custom alerts for ticker {ticker}: {e}")
    except Exception as e:
        logger.error(f"Error checking custom alerts: {e}")

def schedule_user_briefing(chat_id: int, time_str: str, timezone_str: str, bot=None):
    """
    Add or replace a user's scheduled daily briefing job.
    """
    global _bot_instance
    if bot is None:
        bot = _bot_instance
    job_id = f"briefing_{chat_id}"
    try:
        hour, minute = map(int, time_str.split(':'))
    except Exception as e:
        logger.error(f"Invalid briefing time format '{time_str}' for user {chat_id}: {e}")
        return
        
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        
    scheduler.add_job(
        send_daily_briefing,
        CronTrigger(hour=hour, minute=minute, timezone=timezone_str),
        id=job_id,
        args=[chat_id, bot]
    )
    logger.info(f"Scheduled briefing job '{job_id}' for {time_str} ({timezone_str}).")

def schedule_user_evening_briefing(chat_id: int, time_str: str, timezone_str: str, bot=None):
    """
    Add or replace a user's scheduled daily evening briefing job.
    """
    global _bot_instance
    if bot is None:
        bot = _bot_instance
    job_id = f"evening_briefing_{chat_id}"
    try:
        hour, minute = map(int, time_str.split(':'))
    except Exception as e:
        logger.error(f"Invalid evening briefing time format '{time_str}' for user {chat_id}: {e}")
        return
        
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        
    scheduler.add_job(
        send_evening_briefing,
        CronTrigger(hour=hour, minute=minute, timezone=timezone_str),
        id=job_id,
        args=[chat_id, bot]
    )
    logger.info(f"Scheduled evening briefing job '{job_id}' for {time_str} ({timezone_str}).")

def init_scheduler(bot):
    """
    Load scheduled briefings for all registered users on startup and start the scheduler.
    """
    global _bot_instance
    _bot_instance = bot
    
    # Load all completed users and schedule their briefings
    conn = database.get_db_connection()
    rows = conn.execute("SELECT chat_id, preferences FROM users WHERE onboarding_status = 'completed'").fetchall()
    conn.close()
    
    for row in rows:
        chat_id = row['chat_id']
        try:
            prefs = json.loads(row['preferences']) if row['preferences'] else {}
        except Exception:
            prefs = {}
        briefing_time = prefs.get('briefing_time')
        evening_briefing_time = prefs.get('evening_briefing_time')
        timezone = prefs.get('timezone', 'Asia/Kolkata')
        
        if briefing_time:
            schedule_user_briefing(chat_id, briefing_time, timezone, bot)
        if evening_briefing_time:
            schedule_user_evening_briefing(chat_id, evening_briefing_time, timezone, bot)
            
    # Add watchlist anomaly checking job (runs every 30 minutes)
    scheduler.add_job(
        check_watchlist_anomalies,
        'interval',
        minutes=30,
        id='watchlist_scanner',
        args=[bot]
    )
    
    # Add custom alerts checking job (runs every 15 minutes)
    scheduler.add_job(
        check_custom_alerts,
        'interval',
        minutes=15,
        id='custom_alerts_scanner',
        args=[bot]
    )
    
    scheduler.start()
    logger.info("Background scheduler started.")
