import yfinance as yf
import pandas as pd
import logging
from datetime import datetime
import requests

logger = logging.getLogger(__name__)

def _get_ticker(symbol: str) -> yf.Ticker:
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    return yf.Ticker(symbol, session=session)

def _search_fallback(query: str) -> str:
    """
    Search fallback to gather data via Web Search when API is rate-limited.
    """
    try:
        from tools.web_tools import search_web
        return search_web(query, max_results=3)
    except Exception as e:
        logger.error(f"Fallback search failed: {e}")
        return f"Error executing search-based fallback: {str(e)}"

def get_stock_price(ticker: str) -> str:
    """
    Get current stock price, change, percent change, daily range, and volume for a ticker.
    """
    ticker = ticker.upper().strip()
    try:
        t = _get_ticker(ticker)
        info = t.info
        
        current_price = info.get('currentPrice') or info.get('regularMarketPrice')
        prev_close = info.get('regularMarketPreviousClose') or info.get('previousClose')
        
        if current_price is None:
            # Fallback to historical data
            hist = t.history(period="2d")
            if not hist.empty:
                current_price = hist['Close'].iloc[-1]
                if len(hist) > 1:
                    prev_close = hist['Close'].iloc[-2]
                else:
                    prev_close = current_price
            else:
                raise ValueError("No historical price found.")
        
        price_change = current_price - prev_close if prev_close else 0
        pct_change = (price_change / prev_close) * 100 if prev_close else 0
        
        currency = info.get('currency', 'USD')
        name = info.get('longName') or info.get('shortName') or ticker
        
        result = (
            f"**{name} ({ticker})**\n"
            f"Current Price: {current_price:.2f} {currency}\n"
            f"Change: {price_change:+.2f} ({pct_change:+.2f}%)\n"
            f"Day Range: {info.get('regularMarketDayLow', 'N/A')} - {info.get('regularMarketDayHigh', 'N/A')}\n"
            f"52-Week Range: {info.get('fiftyTwoWeekLow', 'N/A')} - {info.get('fiftyTwoWeekHigh', 'N/A')}\n"
            f"Volume: {info.get('regularMarketVolume', info.get('volume', 0)):,}\n"
            f"Market Cap: {info.get('marketCap', 0):,}\n"
        )
        return result
    except Exception as e:
        logger.warning(f"Yahoo Finance API rate-limited for {ticker} stock price. Falling back to search. Error: {e}")
        fallback_query = f"{ticker} stock price Google Finance today"
        search_res = _search_fallback(fallback_query)
        return (
            f"⚠️ **{ticker} (API Rate-Limited Fallback)**\n"
            f"Real-time API is rate-limited. Gathered the following details via live web search:\n\n"
            f"{search_res}"
        )

def get_company_financials(ticker: str) -> str:
    """
    Get key financial metrics, revenue, EBITDA, margins, ratios, and growth rates.
    """
    ticker = ticker.upper().strip()
    try:
        t = _get_ticker(ticker)
        info = t.info
        
        name = info.get('longName') or ticker
        currency = info.get('financialCurrency') or info.get('currency', 'USD')
        
        financials = (
            f"**Financial Profile: {name} ({ticker})**\n"
            f"Sector: {info.get('sector', 'N/A')} | Industry: {info.get('industry', 'N/A')}\n\n"
            f"**Key Metrics:**\n"
            f"• Revenue (TTM): {info.get('totalRevenue', 0):,} {currency}\n"
            f"• Revenue Growth (YoY): {info.get('revenueGrowth', 0) * 100:+.2f}%\n"
            f"• Gross Profit (TTM): {info.get('grossProfits', 0):,} {currency}\n"
            f"• Gross Margin: {info.get('grossMargins', 0) * 100:.2f}%\n"
            f"• EBITDA: {info.get('ebitda', 0):,} {currency}\n"
            f"• Operating Margin: {info.get('operatingMargins', 0) * 100:.2f}%\n"
            f"• Net Income to Common (TTM): {info.get('netIncomeToCommon', 0):,} {currency}\n"
            f"• Profit Margin: {info.get('profitMargins', 0) * 100:.2f}%\n"
            f"• Free Cash Flow (TTM): {info.get('freeCashflow', 0):,} {currency}\n\n"
            f"**Valuation & Ratios:**\n"
            f"• Trailing P/E: {info.get('trailingPE', 'N/A')}\n"
            f"• Forward P/E: {info.get('forwardPE', 'N/A')}\n"
            f"• EV/EBITDA: {info.get('enterpriseToEbitda', 'N/A')}\n"
            f"• Debt-to-Equity Ratio: {info.get('debtToEquity', 'N/A')}\n"
            f"• Return on Equity (ROE): {info.get('returnOnEquity', 0) * 100:.2f}%\n"
        )
        return financials
    except Exception as e:
        logger.warning(f"Yahoo Finance API rate-limited for {ticker} financials. Falling back to search. Error: {e}")
        fallback_query = f"{ticker} revenue growth PE ratio market cap financials"
        search_res = _search_fallback(fallback_query)
        return (
            f"⚠️ **{ticker} Financials (API Rate-Limited Fallback)**\n"
            f"Real-time API is rate-limited. Gathered the following details via live web search:\n\n"
            f"{search_res}"
        )

def get_company_news(ticker: str) -> str:
    """
    Get recent news articles for a company.
    """
    ticker = ticker.upper().strip()
    try:
        t = _get_ticker(ticker)
        news = t.news
        if not news:
            raise ValueError("No news found.")
            
        result = f"**Recent News for {ticker}:**\n\n"
        for idx, item in enumerate(news[:5]):
            title = item.get('title')
            publisher = item.get('publisher')
            link = item.get('link')
            pub_time = item.get('providerPublishTime')
            date_str = ""
            if pub_time:
                date_str = datetime.fromtimestamp(pub_time).strftime('%Y-%m-%d %H:%M')
            
            result += f"{idx+1}. **{title}**\n"
            if publisher or date_str:
                result += f"   _Source: {publisher} ({date_str})_\n"
            result += f"   [Read Article]({link})\n\n"
        return result
    except Exception as e:
        logger.warning(f"Yahoo Finance API rate-limited for {ticker} news. Falling back to search. Error: {e}")
        fallback_query = f"{ticker} stock news market updates"
        search_res = _search_fallback(fallback_query)
        return (
            f"⚠️ **{ticker} News (API Rate-Limited Fallback)**\n"
            f"Real-time API is rate-limited. Gathered the following updates via live web search:\n\n"
            f"{search_res}"
        )

def get_market_indices() -> str:
    """
    Get performance summaries of major market indices (S&P 500, Nasdaq, Dow Jones, Russell 2000, 10Y Yield).
    """
    indices = {
        "^GSPC": "S&P 500",
        "^IXIC": "Nasdaq Composite",
        "^DJI": "Dow Jones Industrial Average",
        "^RUT": "Russell 2000",
        "^TNX": "US 10-Year Treasury Yield"
    }
    
    result = "**Global Market Summary**\n"
    result += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    
    api_failed = False
    for symbol, name in indices.items():
        try:
            t = _get_ticker(symbol)
            hist = t.history(period="2d")
            if hist.empty:
                raise ValueError("Empty historical data.")
            
            current = hist['Close'].iloc[-1]
            prev = hist['Close'].iloc[-2] if len(hist) > 1 else current
            change = current - prev
            pct_change = (change / prev) * 100 if prev else 0
            
            if symbol == "^TNX":
                result += f"• **{name}**: {current:.2f}% (Change: {change:+.3f} pts)\n"
            else:
                result += f"• **{name}**: {current:,.2f} | {change:+.2f} ({pct_change:+.2f}%)\n"
        except Exception as e:
            logger.warning(f"Yahoo Finance API rate-limited for index {symbol}. Error: {e}")
            api_failed = True
            break
            
    if api_failed:
        # Fall back to web search summary for major indices
        logger.info("Yahoo Finance indices rate-limited. Falling back to search index summary.")
        fallback_res = _search_fallback("S&P 500 Nasdaq Dow Jones index performance today")
        return (
            f"⚠️ **Global Market Summary (API Rate-Limited Fallback)**\n"
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Real-time indices API is rate-limited. Gathered the following performance details via web search:\n\n"
            f"{fallback_res}"
        )
        
    return result

def get_sec_filings(ticker: str) -> str:
    """
    Get recent SEC filings (10-K, 10-Q, 8-K) for a company using web search.
    """
    ticker = ticker.upper().strip()
    query = f"{ticker} SEC filings SEC.gov recent"
    try:
        from tools.web_tools import search_web
        search_res = search_web(query, max_results=4)
        return (
            f"**Recent SEC Filings for {ticker}:**\n\n"
            f"Gathered from SEC EDGAR and official filings directories:\n\n"
            f"{search_res}"
        )
    except Exception as e:
        logger.error(f"Error fetching SEC filings for {ticker}: {e}")
        return f"Failed to retrieve SEC filings for {ticker}: {str(e)}"

def get_earnings_calendar(ticker: str = None) -> str:
    """
    Get upcoming earnings release dates.
    If ticker is provided, gets specific scheduled date.
    If no ticker is provided, gets general upcoming releases for major companies.
    """
    try:
        if ticker:
            ticker = ticker.upper().strip()
            t = _get_ticker(ticker)
            calendar = t.calendar
            
            # yfinance returns dictionary or df for calendar
            if calendar is not None:
                # Format the calendar
                if isinstance(calendar, dict):
                    # Python dictionary format
                    date_val = calendar.get('Earnings Date', ['N/A'])[0]
                    if hasattr(date_val, 'strftime'):
                        date_str = date_val.strftime('%Y-%m-%d')
                    else:
                        date_str = str(date_val)
                    avg = calendar.get('Earnings Average', [0.0])[0]
                    low = calendar.get('Earnings Low', [0.0])[0]
                    high = calendar.get('Earnings High', [0.0])[0]
                    
                    result = (
                        f"**Upcoming Earnings: {ticker}**\n"
                        f"• **Expected Earnings Date:** {date_str}\n"
                        f"• **EPS Average Estimate:** {avg:.2f}\n"
                        f"• **EPS Range:** {low:.2f} - {high:.2f}\n"
                    )
                else:
                    # Pandas DataFrame format
                    result = f"**Upcoming Earnings Calendar for {ticker}:**\n\n{calendar.to_markdown()}"
                return result
            else:
                # Fallback to search if calendar is empty
                query = f"{ticker} upcoming earnings date release"
                from tools.web_tools import search_web
                search_res = search_web(query, max_results=3)
                return (
                    f"**Upcoming Earnings: {ticker} (Search Fallback)**\n"
                    f"Earnings calendar not directly populated in standard feeds. Recent updates:\n\n"
                    f"{search_res}"
                )
        else:
            # General earnings calendar this week
            from tools.web_tools import search_web
            search_res = search_web("major earnings reports release scheduled this week", max_results=4)
            return (
                f"**Earnings Calendar (This Week):**\n\n"
                f"{search_res}"
            )
    except Exception as e:
        logger.error(f"Error fetching earnings calendar: {e}")
        # Search fallback on exception
        fallback_ticker = ticker if ticker else "market"
        query = f"{fallback_ticker} upcoming earnings calendar releases this week"
        try:
            from tools.web_tools import search_web
            return search_web(query, max_results=3)
        except Exception:
            return f"Failed to retrieve earnings calendar: {str(e)}"

def get_economic_calendar() -> str:
    """
    Get major macroeconomic events (CPI, GDP, interest rate decisions) scheduled for this week.
    """
    query = "major macroeconomic events economic calendar CPI GDP FOMC this week"
    try:
        from tools.web_tools import search_web
        search_res = search_web(query, max_results=5)
        return (
            f"**Macroeconomic Calendar (This Week):**\n\n"
            f"Key indicators, rate announcements, and speeches:\n\n"
            f"{search_res}"
        )
    except Exception as e:
        logger.error(f"Error fetching economic calendar: {e}")
        return f"Failed to retrieve economic calendar: {str(e)}"
