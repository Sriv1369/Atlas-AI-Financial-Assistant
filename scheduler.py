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

scheduler = AsyncIOScheduler()

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
            t = yf.Ticker(ticker)
            # Fetch 1 day interval data
            hist = t.history(period="1d")
            if hist.empty:
                continue
                
            info = t.info
            current_price = info.get('currentPrice') or info.get('regularMarketPrice') or hist['Close'].iloc[-1]
            prev_close = info.get('regularMarketPreviousClose') or info.get('previousClose')
            
            if not prev_close:
                continue
                
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

def schedule_user_briefing(chat_id: int, time_str: str, timezone_str: str, bot):
    """
    Add or replace a user's scheduled daily briefing job.
    """
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

def init_scheduler(bot):
    """
    Load scheduled briefings for all registered users on startup and start the scheduler.
    """
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
        timezone = prefs.get('timezone', 'Asia/Kolkata')
        
        if briefing_time:
            schedule_user_briefing(chat_id, briefing_time, timezone, bot)
            
    # Add watchlist anomaly checking job (runs every 30 minutes)
    scheduler.add_job(
        check_watchlist_anomalies,
        'interval',
        minutes=30,
        id='watchlist_scanner',
        args=[bot]
    )
    
    scheduler.start()
    logger.info("Background scheduler started.")
