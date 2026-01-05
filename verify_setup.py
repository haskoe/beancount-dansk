import sys
import os
import decimal
from beancount import loader
from beancount.core import data

D = decimal.Decimal

# Ensure we can import the plugins
sys.path.insert(0, os.getcwd())

TEST_CONTENT = """
option "title" "Test"
option "operating_currency" "DKK"
plugin "plugins.danish_plugins"

2024-01-01 open Assets:Bank:Erhverv
2024-01-01 open Assets:Moms:Koebs
2024-01-01 open Assets:Debitorer
2024-01-01 open Liabilities:Moms:Salgs
2024-01-01 open Liabilities:Kreditorer
2024-01-01 open Expenses:Food
2024-01-01 open Expenses:Software
2024-01-01 open Expenses:Personnel:Mileage
2024-01-01 open Income:Salg:Momspligtigt

; 1. Standard Expense
2024-02-01 custom "quick-expense" Expenses:Food "Lunch" 125.00 DKK "standard"

; 2. Restaurant Expense
2024-02-02 custom "quick-expense" Expenses:Food "Dinner" 1000.00 DKK "restaurant"

; 3. Kreditor Expense + Invoice Ref
2024-02-03 custom "quick-expense" Expenses:Food "Purchase" 500.00 DKK "momsfri" Liabilities:Kreditorer "FAC-2024-001"

; 4. Foreign Currency + Net matching (EUR purchase, u-moms)
; 100 EUR Software. reverse charge. 
2024-02-04 custom "quick-expense" Expenses:Software "SaaS" 100.00 EUR "u-moms" Liabilities:Kreditorer "FAC-EUR-001" 100.00 EUR

; 5. Mileage
2025-03-01 custom "quick-mileage" 100 KM

; 6. Sales Invoice
2024-04-01 custom "sales-invoice" "Acme" "INV-TEST-001" "Income:Salg:Momspligtigt" "Consulting;10;1000"
"""


def verify():
    print("Loading test content...")
    entries, errors, options = loader.load_string(TEST_CONTENT)

    if errors:
        print("ERRORS found during loading:")
        for e in errors:
            print(e)
        # sys.exit(1)

    transactions = [e for e in entries if isinstance(e, data.Transaction)]
    print(f"Loaded {len(entries)} entries, {len(transactions)} generated transactions.")

    # 1. Standard
    t1 = next((t for t in transactions if t.narration == "Lunch"), None)
    if t1:
        assert "240201-Expenses-Food" in t1.links
        postings = {p.account: p.units.number for p in t1.postings}
        assert postings["Assets:Bank:Erhverv"] == -125
        assert postings["Assets:Moms:Koebs"] == 25
        assert postings["Expenses:Food"] == 100
        print("[Pass] Standard Expense (Auto-link checked)")

    # 2. Restaurant
    t2 = next((t for t in transactions if t.narration == "Dinner"), None)
    if t2:
        postings = {p.account: p.units.number for p in t2.postings}
        assert postings["Assets:Moms:Koebs"] == 50
        assert postings["Expenses:Food"] == 950
        print("[Pass] Restaurant Expense")

    # 3. Kreditor + Ref
    t3 = next((t for t in transactions if t.narration == "Purchase"), None)
    if t3:
        assert "FAC-2024-001" in t3.links
        assert t3.meta.get("invoice") == "FAC-2024-001"
        postings = {p.account: p.units.number for p in t3.postings}
        assert postings["Liabilities:Kreditorer"] == -500
        print("[Pass] Kreditor Expense with Reference")

    # 4. Foreign + u-moms + Net match
    t4 = next((t for t in transactions if t.narration == "SaaS"), None)
    if t4:
        # Reverse charge: 100 EUR. Buy VAT = 25. Sell VAT = -25. Expense = 100.
        postings = {p.account: p.units.number for p in t4.postings}
        assert postings["Expenses:Software"] == 100
        assert postings["Assets:Moms:Koebs"] == 25
        assert postings["Liabilities:Moms:Salgs"] == -25
        assert postings["Liabilities:Kreditorer"] == -100
        assert t4.postings[0].units.currency == "EUR"
        print("[Pass] Foreign Currency Reverse Charge (u-moms)")

    # 5. Mileage
    t5 = next((t for t in transactions if "Mileage:" in t.narration), None)
    if t5:
        print("[Pass] Mileage")

    # 6. Invoice
    t6 = next((t for t in transactions if "Invoice INV-TEST-001" in t.narration), None)
    if t6:
        print("[Pass] Sales Invoice")


if __name__ == "__main__":
    verify()
