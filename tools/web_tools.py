import logging
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

def search_web(query: str, max_results: int = 5) -> str:
    """
    Search the web for general news, macroeconomic events, and corporate actions.
    """
    try:
        logger.info(f"Searching the web for: {query}")
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            
            if not results:
                return f"No web search results found for query: '{query}'."
                
            formatted_results = f"**Web Search Results for '{query}':**\n\n"
            for i, r in enumerate(results):
                title = r.get('title', 'No Title')
                snippet = r.get('body', '')
                url = r.get('href', '')
                formatted_results += f"{i+1}. **{title}**\n"
                formatted_results += f"   {snippet}\n"
                if url:
                    formatted_results += f"   [Read More]({url})\n"
                formatted_results += "\n"
                
            return formatted_results
    except Exception as e:
        logger.error(f"Error during web search: {e}")
        return f"Failed to perform web search: {str(e)}"

def search_financial_news(query: str, max_results: int = 5) -> str:
    """
    Search specifically for financial or corporate news.
    """
    # Simply prefix with financial terms to focus DDG search
    financial_query = f"{query} finance stock market corporate earnings"
    return search_web(financial_query, max_results)
