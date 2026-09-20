import re
import logging
import datetime
from email.utils import parsedate_to_datetime
import base64
from googleapiclient.discovery import build

import database
from tools.google_tools import get_google_creds

logger = logging.getLogger(__name__)

# Standard Category Mapping Keywords
CATEGORY_KEYWORDS = {
    'Food & Dining': [
        'swiggy', 'zomato', 'mcdonald', 'starbucks', 'kfc', 'burger king', 'pizza', 'domino',
        'subway', 'restaurant', 'cafe', 'eatery', 'barbeque', 'diner', 'bistro', 'foodpanda',
        'uber eats', 'faasos', 'behrouz', 'chai point', 'chaayos'
    ],
    'Groceries': [
        'blinkit', 'zepto', 'bigbasket', 'instamart', 'dmart', 'nature basket', 'supermarket',
        'grocery', 'spencer', 'more retail', 'reliance fresh', 'walmart', 'trader joe', 'whole foods'
    ],
    'Shopping': [
        'amazon', 'flipkart', 'myntra', 'ajio', 'nykaa', 'zara', 'h&m', 'nike', 'adidas',
        'uniqlo', 'croma', 'reliance digital', 'apple', 'meesho', 'tata cliq', 'retail', 'store'
    ],
    'Travel & Transport': [
        'uber', 'ola', 'rapido', 'irctc', 'makemytrip', 'goibibo', 'cleartrip', 'indigo',
        'air india', 'spicejet', 'vistara', 'flight', 'airline', 'railway', 'train', 'metro',
        'petrol', 'fuel', 'hpcl', 'bpcl', 'iocl', 'shell', 'fastag', 'toll'
    ],
    'Bills & Utilities': [
        'bescom', 'tata power', 'electricity', 'water', 'piped gas', 'adani electricity',
        'jio', 'airtel', 'vodafone', 'vi', 'broadband', 'act fibernet', 'billdesk', 'recharge',
        'tatasky', 'dth', 'postpaid', 'utility'
    ],
    'Entertainment & Subscriptions': [
        'netflix', 'spotify', 'prime video', 'youtube', 'hotstar', 'disney', 'bookmyshow',
        'pvr', 'inox', 'apple.com/bill', 'google play', 'steam', 'playstation', 'audible', 'kindle'
    ],
    'Health & Medical': [
        'apollo', 'pharmeasy', '1mg', 'netmeds', 'medplus', 'hospital', 'pharmacy',
        'clinic', 'diagnostic', 'dr.', 'cult.fit', 'gym', 'fitness', 'max healthcare'
    ],
    'Investments & Wealth': [
        'zerodha', 'groww', 'upstox', 'angel one', 'kuvera', 'coin', 'mutual fund',
        'sip', 'nps', 'ppf', 'lic', 'insurance', 'hdfc life', 'icici pru', 'cred'
    ],
    'Salary & Income': [
        'salary', 'payroll', 'direct deposit', 'dividend', 'interest credit', 'stipend', 'bonus'
    ]
}

def classify_category(text: str, merchant: str = None) -> str:
    """
    Classify a transaction into a spending category based on merchant name and email text.
    """
    combined = f"{merchant or ''} {text}".lower()
    
    # Check Salary & Income first if explicitly credited with salary/payroll/dividend/bonus
    for kw in CATEGORY_KEYWORDS['Salary & Income']:
        if re.search(r'\b' + re.escape(kw) + r'\b', combined):
            return 'Salary & Income'
            
    for category, keywords in CATEGORY_KEYWORDS.items():
        if category == 'Salary & Income':
            continue
        for kw in keywords:
            # If keyword is short (<= 4 chars like cred, sip, lic, vi), enforce word boundaries
            if len(kw) <= 4:
                if re.search(r'\b' + re.escape(kw) + r'\b', combined):
                    return category
            else:
                if kw in combined:
                    return category
                
    if any(term in combined for term in ['transfer', 'upi/', 'sent to', 'received from', 'p2p']):
        return 'Transfers & P2P'
        
    return 'Other'

def clean_merchant_name(raw_merchant: str) -> str:
    """
    Clean up messy merchant handles (e.g. 'swiggy@icici', 'PAYTM*AMAZON INDIA') into readable names.
    """
    if not raw_merchant:
        return 'Unknown'
        
    m = raw_merchant.strip()
    
    # Remove UPI handles like @icici, @okaxis, @okhdfcbank
    if '@' in m:
        m = m.split('@')[0]
        
    # Remove prefix noise like 'VPA', 'UPI/', 'PAYTM*', 'NEFT-'
    m = re.sub(r'^(?:vpa\s*|upi\s*\/\s*\d*\/?|paytm\s*\*\s*|neft\s*-\s*|imps\s*-\s*)', '', m, flags=re.IGNORECASE)
    
    # Remove common trailing noise
    m = re.sub(r'[\.\,\:\-\_]+$', '', m).strip()
    
    # Capitalize into Title Case so all words are formatted properly (e.g. Amazon India)
    if len(m) > 1:
        m = m.title()
        
    return m[:40] if m else 'Unknown'

def parse_transaction_email(subject: str, sender: str, date_str: str, body: str) -> dict | None:
    """
    Extract transaction details from bank/UPI/credit card notification emails.
    Returns a dict with: date, amount, currency, transaction_type, merchant, category, account_ref, raw_snippet
    or None if no financial transaction could be parsed.
    """
    combined_text = f"{subject}\n{body}"
    
    # Ignore marketing, OTPs, promotional emails
    lower_text = combined_text.lower()
    if any(skip in lower_text for skip in [
        'one time password', 'otp', 'verification code', 'apply now', 'pre-approved',
        'special offer', 'congratulations! you are eligible', 'statement for the period'
    ]) and not any(alert in lower_text for alert in ['debited', 'credited', 'spent on', 'paid to']):
        return None

    # 1. Determine Transaction Type (DEBIT vs CREDIT)
    credit_patterns = [
        r'\b(?:credited\s+(?:with|by|to|for)|has\s+been\s+credited|received\s+(?:rs\.?|inr|\$)|salary\s+credit|money\s+received|refund\s+(?:of|received)|cashback\s+of|direct\s+deposit)\b'
    ]
    debit_patterns = [
        r'\b(?:debited\s+(?:by|for|from|with)|has\s+been\s+debited|spent\s+on|paid\s+to|sent\s+(?:rs\.?|inr|\$)|money\s+sent|purchase\s+at|charged\s+(?:for|at)|using\s+your\s+card|used\s+at)\b'
    ]
    
    is_credit = any(re.search(p, combined_text, re.IGNORECASE) for p in credit_patterns)
    is_debit = any(re.search(p, combined_text, re.IGNORECASE) for p in debit_patterns)
    
    # Note: Avoid matching "credit card" as a credit deposit
    lower_no_credit_card = re.sub(r'credit\s+card', '', lower_text)

    if is_credit and not is_debit:
        txn_type = 'CREDIT'
    elif is_debit:
        txn_type = 'DEBIT'
    elif 'received' in lower_no_credit_card or 'credited' in lower_no_credit_card:
        txn_type = 'CREDIT'
    elif 'debited' in lower_text or 'spent' in lower_text or 'paid' in lower_text or 'card ending' in lower_text:
        txn_type = 'DEBIT'
    else:
        # Unable to determine whether debit or credit
        return None

    # 2. Extract Amount & Currency
    # Look for INR, Rs, ₹, USD, $, EUR, € followed by numeric amount
    amount = None
    currency = 'INR'
    
    amt_regex = re.search(
        r'(?:(INR|Rs\.?|₹|\$|USD|EUR|€)\s*([\d,]+(?:\.\d{1,2})?))|(?:([\d,]+(?:\.\d{1,2})?)\s*(INR|Rs\.?|₹))',
        combined_text,
        re.IGNORECASE
    )
    
    if amt_regex:
        if amt_regex.group(1):
            curr_match = amt_regex.group(1)
            amt_str = amt_regex.group(2)
        else:
            amt_str = amt_regex.group(3)
            curr_match = amt_regex.group(4)
            
        # Normalize Currency
        if curr_match in ['$', 'USD']:
            currency = 'USD'
        elif curr_match in ['€', 'EUR']:
            currency = 'EUR'
        else:
            currency = 'INR'
            
        # Clean amount string
        try:
            cleaned_num = amt_str.replace(',', '').strip()
            amount = float(cleaned_num)
        except ValueError:
            amount = None

    if not amount or amount <= 0:
        return None

    # 3. Extract Merchant / Beneficiary / Payee
    merchant = None
    merchant_patterns = [
        r'\b(?:towards|\bto\b|\bat\b|for\s+info:|info:|paid\s+to|transfer\s+to|received\s+from|used\s+at)\s+(?:VPA\s*)?([A-Za-z0-9\.\-\_\s@]{2,45}?)(?:\s+on|\s+ref|\s+using|\s+avl|\.|\n|$)',
    ]
    # Check body first as it contains the actual transaction details
    generic_words = {'account', 'card', 'your', 'bank', 'customer', 'vpa', 'dear', 'alert', 'unknown'}
    for p in merchant_patterns:
        match = re.search(p, body, re.IGNORECASE)
        if match:
            candidate = clean_merchant_name(match.group(1).strip())
            if candidate and candidate.lower() not in generic_words and not any(candidate.lower() == gw for gw in generic_words):
                merchant = candidate
                break
                
    if not merchant:
        # Fallback to checking subject
        for p in merchant_patterns:
            match = re.search(p, subject, re.IGNORECASE)
            if match:
                candidate = clean_merchant_name(match.group(1).strip())
                if candidate and candidate.lower() not in generic_words:
                    merchant = candidate
                    break

    if not merchant:
        merchant = 'Direct Transfer / Merchant' if txn_type == 'DEBIT' else 'Direct Deposit / Sender'

    # 4. Extract Account / Card reference
    account_ref = None
    acc_match = re.search(r'(?:a\/c|account|acct|card|ending)\s*(?:no\.?|ending)?\s*(?:with\s*)?([xX*]*\d{3,4})', combined_text, re.IGNORECASE)
    if acc_match:
        account_ref = f"**{acc_match.group(1).replace('x','').replace('X','').replace('*','')}"

    # 5. Extract Date
    iso_date = None
    if date_str:
        try:
            dt = parsedate_to_datetime(date_str)
            iso_date = dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
            
    if not iso_date:
        # Fallback to current UTC/local date
        iso_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 6. Categorize Transaction
    category = classify_category(combined_text, merchant)
    if txn_type == 'CREDIT' and category == 'Other':
        category = 'Salary & Income'

    # 7. Raw Snippet for verification
    raw_snippet = subject if subject else (body[:120].strip() if body else '')

    return {
        'date': iso_date,
        'amount': amount,
        'currency': currency,
        'transaction_type': txn_type,
        'merchant': merchant,
        'category': category,
        'account_ref': account_ref or 'A/C',
        'raw_snippet': raw_snippet[:150]
    }

def sync_email_transactions(chat_id: int, days_back: int = 30, custom_query: str = None) -> str:
    """
    Search Gmail for bank and payment transaction emails, parse amounts, debits/credits,
    merchants and categories, and record them in the database ledger.
    """
    creds = get_google_creds(chat_id)
    if not creds:
        return "Your Google account is not connected. Type 'connect google' or use `get_google_auth_link` to link it."

    try:
        service = build('gmail', 'v1', credentials=creds)
        
        # Calculate date threshold
        since_date = (datetime.datetime.now() - datetime.timedelta(days=days_back)).strftime('%Y/%m/%d')
        
        # Construct search query focused on bank & payment transactions
        if custom_query:
            search_query = f"after:{since_date} ({custom_query})"
        else:
            search_query = (
                f'after:{since_date} '
                f'(subject:(debited OR credited OR "spent" OR "transaction alert" OR "UPI" OR "payment" OR "paid to" OR "received from") '
                f'OR "debited by" OR "credited with" OR "account ending" OR "card ending")'
            )

        logger.info(f"Syncing transactions for chat_id {chat_id} with query: {search_query}")
        
        # Execute query to list matching messages
        results = service.users().messages().list(userId='me', q=search_query, maxResults=100).execute()
        messages = results.get('messages', [])
        
        if not messages:
            return f"No transaction emails found in Gmail for the last {days_back} days matching financial alert filters."

        # Fetch existing processed message IDs to deduplicate O(1)
        existing_ids = database.get_existing_transaction_message_ids(chat_id)
        
        new_messages = [m for m in messages if m['id'] not in existing_ids]
        if not new_messages:
            return f"Your transactions are already up to date! Scanned {len(messages)} recent bank emails; 0 new transactions needed importing."

        saved_count = 0
        total_debits = 0.0
        total_credits = 0.0
        
        for msg in new_messages:
            msg_id = msg['id']
            try:
                msg_data = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
                headers = msg_data.get('payload', {}).get('headers', [])
                headers_dict = {h['name'].lower(): h['value'] for h in headers}
                
                subject = headers_dict.get('subject', '')
                sender = headers_dict.get('from', '')
                date_header = headers_dict.get('date', '')
                snippet = msg_data.get('snippet', '')
                
                # Extract text body
                body_parts = []
                def extract_parts(part):
                    mime = part.get('mimeType', '')
                    data = part.get('body', {}).get('data', '')
                    if mime in ['text/plain', 'text/html'] and data:
                        try:
                            body_parts.append(base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore'))
                        except Exception:
                            pass
                    if 'parts' in part:
                        for subpart in part['parts']:
                            extract_parts(subpart)
                            
                payload = msg_data.get('payload', {})
                if 'parts' in payload:
                    for part in payload['parts']:
                        extract_parts(part)
                else:
                    data = payload.get('body', {}).get('data', '')
                    if data:
                        try:
                            body_parts.append(base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore'))
                        except Exception:
                            pass
                            
                body_text = "\n".join(body_parts) if body_parts else snippet
                
                # Parse transaction
                parsed = parse_transaction_email(subject, sender, date_header, body_text)
                if parsed:
                    inserted = database.save_transaction(
                        chat_id=chat_id,
                        message_id=msg_id,
                        date=parsed['date'],
                        amount=parsed['amount'],
                        currency=parsed['currency'],
                        transaction_type=parsed['transaction_type'],
                        merchant=parsed['merchant'],
                        category=parsed['category'],
                        account_ref=parsed['account_ref'],
                        raw_snippet=parsed['raw_snippet']
                    )
                    if inserted:
                        saved_count += 1
                        if parsed['transaction_type'] == 'DEBIT':
                            total_debits += parsed['amount']
                        else:
                            total_credits += parsed['amount']
                            
            except Exception as e:
                logger.warning(f"Error parsing message {msg_id}: {e}")
                continue

        result = (
            f"✅ **Gmail Transaction Sync Complete**\n\n"
            f"• **New Transactions Added:** {saved_count}\n"
            f"• **Total New Expenses (Debited):** ₹{total_debits:,.2f}\n"
            f"• **Total New Income/Refunds (Credited):** ₹{total_credits:,.2f}\n"
            f"• **Scanned Period:** Last {days_back} days ({len(messages)} matching bank alerts found)\n\n"
            f"You can now ask me: *'What are my monthly expenses?'* or *'Show recent transactions'* to explore your spending breakdown!"
        )
        return result

    except Exception as e:
        logger.error(f"Error syncing Gmail transactions for {chat_id}: {e}")
        return f"Failed to sync transactions from Gmail: {str(e)}"

def get_monthly_expense_report(chat_id: int, month: int = None, year: int = None) -> str:
    """
    Generate an executive summary of monthly expenses, credits, savings rate,
    category breakdown with percentages, and top merchants.
    Defaults to the current month and year.
    """
    now = datetime.datetime.now()
    if not month:
        month = now.month
    if not year:
        year = now.year

    summary = database.get_monthly_expense_summary(chat_id, year, month)
    categories = database.get_category_breakdown(chat_id, year, month)
    top_merchants = database.get_top_merchants(chat_id, year, month, limit=5)

    month_name = datetime.date(year, month, 1).strftime('%B %Y')
    
    if summary['total_transactions'] == 0:
        return (
            f"No recorded transactions found for **{month_name}**.\n\n"
            f"💡 *Tip:* Ask me to **'sync my transactions from Gmail'** so I can scan your bank alerts and compute your expenses!"
        )

    total_debited = summary['total_debited']
    total_credited = summary['total_credited']
    net_savings = summary['net_savings']
    savings_rate = summary['savings_rate']
    
    cash_flow_emoji = "🟢" if net_savings >= 0 else "🔴"
    cash_flow_sign = "+" if net_savings >= 0 else "-"

    report = (
        f"📊 **Monthly Expense & Cash Flow Report: {month_name}**\n\n"
        f"💳 **Total Expenses (Debited):** ₹{total_debited:,.2f} ({summary['count_debited']} txns)\n"
        f"💰 **Total Income/Credits:** ₹{total_credited:,.2f} ({summary['count_credited']} txns)\n"
        f"{cash_flow_emoji} **Net Cash Flow / Savings:** {cash_flow_sign}₹{abs(net_savings):,.2f} ({savings_rate}% savings rate)\n\n"
    )

    if categories:
        report += "**Category Breakdown:**\n"
        # Category emoji dictionary
        cat_emojis = {
            'Food & Dining': '🍔',
            'Groceries': '🛒',
            'Shopping': '🛍️',
            'Travel & Transport': '🚗',
            'Bills & Utilities': '💡',
            'Entertainment & Subscriptions': '🎬',
            'Health & Medical': '💊',
            'Investments & Wealth': '📈',
            'Salary & Income': '💵',
            'Transfers & P2P': '🔄',
            'Other': '📦'
        }
        for c in categories:
            emoji = cat_emojis.get(c['category'], '•')
            pct = c['percentage']
            # Visual bar (1 block per 10%)
            bar_blocks = int(round(pct / 10))
            bar = '█' * bar_blocks + '░' * (10 - bar_blocks)
            report += f"{emoji} **{c['category']}:** ₹{c['total_amount']:,.2f} ({pct}%) `{bar}`\n"
        report += "\n"

    if top_merchants:
        report += "**Top 5 Spending Merchants:**\n"
        for i, m in enumerate(top_merchants, 1):
            report += f"{i}. **{m['merchant']}:** ₹{m['total_amount']:,.2f} ({m['count']} txns)\n"
        report += "\n"

    report += "_All figures extracted directly from your verified bank notification emails._"
    return report

def list_recent_transactions(chat_id: int, limit: int = 10, transaction_type: str = None, category: str = None) -> str:
    """
    List recent transactions recorded in the database ledger.
    """
    txns = database.get_transactions(
        chat_id=chat_id,
        transaction_type=transaction_type,
        category=category,
        limit=limit
    )

    if not txns:
        filter_desc = f" ({transaction_type or ''} {category or ''})".strip()
        return f"No recorded transactions found{filter_desc}. Type 'sync bank transactions' to scan your emails."

    result = f"🧾 **Recent Transactions (Last {len(txns)}):**\n\n"
    for t in txns:
        sign = "-" if t['transaction_type'] == 'DEBIT' else "+"
        icon = "🔴" if t['transaction_type'] == 'DEBIT' else "🟢"
        currency_sym = "₹" if t['currency'] == 'INR' else "$"
        date_short = t['date'][:10]
        
        result += (
            f"{icon} **{t['merchant']}** | {sign}{currency_sym}{t['amount']:,.2f}\n"
            f"   _Category:_ {t['category']} | _Date:_ {date_short} | _Acc:_ {t['account_ref']}\n\n"
        )

    return result

def export_monthly_expenses_to_sheets(chat_id: int, spreadsheet_name: str = None, month: int = None, year: int = None) -> str:
    """
    Export the monthly transaction ledger and summary into a connected Google Sheet.
    """
    creds = get_google_creds(chat_id)
    if not creds:
        return "Your Google account is not connected. Type 'connect google' to link it."

    now = datetime.datetime.now()
    if not month:
        month = now.month
    if not year:
        year = now.year

    month_name = datetime.date(year, month, 1).strftime('%B_%Y')
    if not spreadsheet_name:
        spreadsheet_name = f"Expenses_{month_name}"

    # Get transactions for month
    start_date = f"{year:04d}-{month:02d}-01"
    end_date = f"{year:04d}-{month:02d}-31"
    txns = database.get_transactions(chat_id=chat_id, start_date=start_date, end_date=end_date, limit=500)

    if not txns:
        return f"No transactions to export for {datetime.date(year, month, 1).strftime('%B %Y')}."

    try:
        service = build('sheets', 'v4', credentials=creds)
        
        # Create a new spreadsheet
        spreadsheet_body = {
            'properties': {
                'title': spreadsheet_name
            }
        }
        sheet = service.spreadsheets().create(body=spreadsheet_body, fields='spreadsheetId,spreadsheetUrl').execute()
        spreadsheet_id = sheet.get('spreadsheetId')
        spreadsheet_url = sheet.get('spreadsheetUrl')

        # Build rows
        headers = ["Date", "Merchant / Payee", "Category", "Type", "Amount", "Currency", "Account", "Snippet"]
        rows = [headers]
        
        for t in txns:
            rows.append([
                t['date'],
                t['merchant'],
                t['category'],
                t['transaction_type'],
                t['amount'],
                t['currency'],
                t['account_ref'],
                t['raw_snippet']
            ])

        # Write data
        body = {'values': rows}
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="Sheet1!A1",
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()

        return (
            f"✅ **Monthly Expenses Exported Successfully!**\n\n"
            f"• **Spreadsheet Title:** {spreadsheet_name}\n"
            f"• **Transactions Exported:** {len(txns)}\n"
            f"• **Spreadsheet Link:** [Open in Google Sheets]({spreadsheet_url})\n"
            f"• **Spreadsheet ID:** `{spreadsheet_id}`"
        )

    except Exception as e:
        logger.error(f"Error exporting expenses to Google Sheets for {chat_id}: {e}")
        return f"Failed to export to Google Sheets: {str(e)}"
