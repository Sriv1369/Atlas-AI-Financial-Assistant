import os
import unittest
import datetime

# Ensure test DB is used
os.environ["DATABASE_PATH"] = "test_assistant.db"

import database
from tools.expense_tools import (
    parse_transaction_email, classify_category, clean_merchant_name,
    get_monthly_expense_report, list_recent_transactions
)

class TestExpenseTracker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database._resolved_db_path = "test_assistant.db"
        database.init_db()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists("test_assistant.db"):
            try:
                os.remove("test_assistant.db")
            except Exception:
                pass

    def setUp(self):
        # Clear transactions table for test chat_id 99999
        database.delete_user_transactions(99999)

    def test_merchant_cleaning(self):
        self.assertEqual(clean_merchant_name("VPA swiggy@icici"), "Swiggy")
        self.assertEqual(clean_merchant_name("UPI/42581234/ZOMATO"), "Zomato")
        self.assertEqual(clean_merchant_name("PAYTM*AMAZON INDIA"), "Amazon India")

    def test_category_classification(self):
        self.assertEqual(classify_category("Order at Swiggy", "Swiggy"), "Food & Dining")
        self.assertEqual(classify_category("Bought groceries at Blinkit", "Blinkit"), "Groceries")
        self.assertEqual(classify_category("Paid for ride", "Uber"), "Travel & Transport")
        self.assertEqual(classify_category("Purchased shoes", "Amazon"), "Shopping")
        self.assertEqual(classify_category("Monthly subscription", "Netflix"), "Entertainment & Subscriptions")
        self.assertEqual(classify_category("Electricity bill paid", "BESCOM"), "Bills & Utilities")
        self.assertEqual(classify_category("Salary for September", "Employer Corp"), "Salary & Income")

    def test_parse_hdfc_debit(self):
        subject = "Alert: Update on your HDFC Bank Account"
        body = "INR 1,450.00 has been debited from account **1234 on 15-09-2026 towards VPA swiggy@hdfcbank."
        date_hdr = "Tue, 15 Sep 2026 14:32:00 +0530"
        
        parsed = parse_transaction_email(subject, "alerts@hdfcbank.net", date_hdr, body)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['transaction_type'], 'DEBIT')
        self.assertEqual(parsed['amount'], 1450.00)
        self.assertEqual(parsed['currency'], 'INR')
        self.assertEqual(parsed['merchant'], 'Swiggy')
        self.assertEqual(parsed['category'], 'Food & Dining')
        self.assertIn('1234', parsed['account_ref'])

    def test_parse_icici_upi(self):
        subject = "Transaction Alert: ICICI Bank"
        body = "Dear Customer, Acct XX567 debited for Rs 899.00 on 14-Sep-26; UPI/42581234/Amazon India."
        date_hdr = "Mon, 14 Sep 2026 10:15:00 +0530"
        
        parsed = parse_transaction_email(subject, "alerts@icicibank.com", date_hdr, body)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['transaction_type'], 'DEBIT')
        self.assertEqual(parsed['amount'], 899.00)
        self.assertEqual(parsed['currency'], 'INR')
        self.assertEqual(parsed['category'], 'Shopping')

    def test_parse_salary_credit(self):
        subject = "Account Credited Alert"
        body = "Your a/c 1234 is credited with INR 85,000.00 on 01-Sep-26 by Salary Direct Deposit."
        date_hdr = "Tue, 01 Sep 2026 09:00:00 +0530"
        
        parsed = parse_transaction_email(subject, "alerts@bank.com", date_hdr, body)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['transaction_type'], 'CREDIT')
        self.assertEqual(parsed['amount'], 85000.00)
        self.assertEqual(parsed['category'], 'Salary & Income')

    def test_parse_usd_credit_card(self):
        subject = "Credit Card Transaction Alert"
        body = "Thank you for using your Card ending with 9876 for USD 45.50 at NETFLIX on 10-Sep-2026."
        date_hdr = "Thu, 10 Sep 2026 12:00:00 +0000"
        
        parsed = parse_transaction_email(subject, "service@amex.com", date_hdr, body)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['transaction_type'], 'DEBIT')
        self.assertEqual(parsed['amount'], 45.50)
        self.assertEqual(parsed['currency'], 'USD')
        self.assertEqual(parsed['category'], 'Entertainment & Subscriptions')

    def test_database_deduplication(self):
        chat_id = 99999
        msg_id = "gmail_msg_001"
        
        # First save should succeed
        res1 = database.save_transaction(
            chat_id=chat_id,
            message_id=msg_id,
            date="2026-09-15 14:32:00",
            amount=500.0,
            currency="INR",
            transaction_type="DEBIT",
            merchant="Swiggy",
            category="Food & Dining",
            account_ref="**1234",
            raw_snippet="Swiggy order"
        )
        self.assertTrue(res1)
        
        # Second save with same message_id should be ignored (deduplicated)
        res2 = database.save_transaction(
            chat_id=chat_id,
            message_id=msg_id,
            date="2026-09-15 14:32:00",
            amount=500.0,
            currency="INR",
            transaction_type="DEBIT",
            merchant="Swiggy",
            category="Food & Dining",
            account_ref="**1234",
            raw_snippet="Swiggy order"
        )
        self.assertFalse(res2)
        
        # Verify message_id is in existing set
        existing = database.get_existing_transaction_message_ids(chat_id)
        self.assertIn(msg_id, existing)

    def test_monthly_calculations(self):
        chat_id = 99999
        # Insert 3 debits and 1 credit in September 2026
        database.save_transaction(chat_id, "m1", "2026-09-01 10:00:00", 50000.0, "INR", "CREDIT", "Employer", "Salary & Income", "**1234", "Salary")
        database.save_transaction(chat_id, "m2", "2026-09-05 12:30:00", 1200.0, "INR", "DEBIT", "Swiggy", "Food & Dining", "**1234", "Food")
        database.save_transaction(chat_id, "m3", "2026-09-10 18:00:00", 800.0, "INR", "DEBIT", "Zomato", "Food & Dining", "**1234", "Food")
        database.save_transaction(chat_id, "m4", "2026-09-12 20:00:00", 3000.0, "INR", "DEBIT", "Amazon", "Shopping", "**1234", "Shopping")

        summary = database.get_monthly_expense_summary(chat_id, 2026, 9)
        self.assertEqual(summary['total_credited'], 50000.0)
        self.assertEqual(summary['total_debited'], 5000.0)
        self.assertEqual(summary['net_savings'], 45000.0)
        self.assertEqual(summary['savings_rate'], 90.0)
        self.assertEqual(summary['count_debited'], 3)
        self.assertEqual(summary['count_credited'], 1)

        breakdown = database.get_category_breakdown(chat_id, 2026, 9)
        # Food & Dining should be 2000 (40%), Shopping should be 3000 (60%)
        self.assertEqual(len(breakdown), 2)
        top_cat = breakdown[0]
        self.assertEqual(top_cat['category'], 'Shopping')
        self.assertEqual(top_cat['total_amount'], 3000.0)
        self.assertEqual(top_cat['percentage'], 60.0)

        # Test report generator output
        report = get_monthly_expense_report(chat_id, month=9, year=2026)
        self.assertIn("Total Expenses (Debited):", report)
        self.assertIn("₹5,000.00", report)
        self.assertIn("Total Income/Credits:", report)
        self.assertIn("₹50,000.00", report)
        self.assertIn("Food & Dining", report)
        self.assertIn("Shopping", report)

        # Test recent transactions
        recent = list_recent_transactions(chat_id, limit=5)
        self.assertIn("Amazon", recent)
        self.assertIn("Swiggy", recent)

if __name__ == '__main__':
    unittest.main()
