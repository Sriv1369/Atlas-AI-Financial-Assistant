# Atlas AI Financial Assistant

An AI-powered Financial Assistant that lives inside Telegram, designed specifically for finance professionals. It operates as an experienced financial analyst rather than a command-driven chatbot, supporting natural conversation, voice notes, document uploads, real-time market data research, and deep productivity integrations with Google Workspace (Gmail, Calendar, Sheets, Drive).

---

## ✨ Features

- **Natural Conversational Experience:** No complex commands, menus, or inline buttons. Communicate naturally through text or voice.
- **Multimodal Intelligence:** 
  - **Voice Notes:** Direct voice note processing using Gemini's native audio parsing.
  - **Documents:** Upload PDFs, Excel sheets, and CSV files for automatic data extraction, summarization, and query execution.
  - **Photos:** Send screenshots of charts or financial tables for direct visual analysis.
- **Real-Time Financial Intelligence:** 
  - Stock prices, volumes, and daily metrics.
  - Financial statements, margins, margins growth, ROE, valuation metrics, etc.
  - Global indices summary (S&P 500, Nasdaq, Dow, Russell 2000, 10Y Yield).
  - Corporate news search powered by Yahoo Finance and live Web Search.
- **Google Workspace Integration:**
  - **Calendar:** Check upcoming meetings or schedule new ones.
  - **Gmail:** Search emails using natural search terms (e.g., *"Find emails about Nvidia"*).
  - **Sheets:** Load spreadsheet ranges and run conversational analytics.
- **Proactive Intelligence:**
  - **Daily Morning Briefs:** Get scheduled reports detailing global market futures, calendar updates, and news on your watchlists.
  - **Watchlist Alerts:** Automatic real-time detection of >5% stock movements on your watchlists, combined with an explanation of *why* it happened.
- **Conversational Onboarding:** Gradually learns your role, watchlist interests, and notification preferences through natural chat instead of form filling.

---

## 🛠️ Tech Stack & Architecture

- **Backend Framework:** Python 3.11+
- **Telegram Wrapper:** `python-telegram-bot` (version 21+)
- **LLM Agent Core:** Gemini 1.5 Pro (SDK: `google-generativeai`)
- **Financial APIs:** `yfinance` (Yahoo Finance API)
- **Web Search Engine:** DuckDuckGo Search API (`duckduckgo-search`)
- **Database:** SQLite
- **Job Scheduler:** `apscheduler`
- **Integrations:** Google APIs (`google-api-python-client`, `google-auth-oauthlib`)

---

## 🚀 Getting Started

### 1. Prerequisites
Ensure you have Python 3.11+ installed.

### 2. Installation
Clone the project and create a virtual environment:
```bash
python -m venv .venv
.venv\Scripts\activate      # On Windows
source .venv/bin/activate    # On macOS/Linux
pip install -r requirements.txt
```

### 3. Configuration
Copy the `.env.template` file to `.env`:
```bash
cp .env.template .env
```
Fill in the configuration fields in `.env`:
- **`TELEGRAM_BOT_TOKEN`**: Get this from `@BotFather` on Telegram.
- **`GEMINI_API_KEY`**: Obtain from [Google AI Studio](https://aistudio.google.com/).
- **`GOOGLE_CLIENT_ID` & `GOOGLE_CLIENT_SECRET`**: (Optional) Register a web application credentials set in your [Google Cloud Console](https://console.cloud.google.com/) with redirect URI: `http://localhost:8080/`. Make sure to enable Gmail API, Google Calendar API, Google Sheets API, and Google Drive API.

### 4. Running the Bot
Launch the backend:
```bash
python main.py
```
Search for your bot username on Telegram and send a message (e.g. `hello` or `/start`) to begin!

---

## 🧩 Google OAuth Setup Details

To connect your Google Workspace account:
1. When you type *"connect google account"* or during onboarding, the bot generates a secure authentication link.
2. Clicking the link takes you to Google's sign-in page.
3. Once authorized, Google redirects you to `http://localhost:8080/`, where a lightweight background server hosted by the assistant captures the access token, stores it securely in the SQLite database, and links it to your Telegram `chat_id`.
4. You will see a success page and can return directly to Telegram!
