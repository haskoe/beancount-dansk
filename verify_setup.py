import sys
import os
from beancount import loader
from beancount.core import data

# Ensure we can import the plugins
sys.path.insert(0, os.getcwd())

TEST_CONTENT = """
option "title" "Test"
option "operating_currency" "DKK"
plugin "plugins.danish_plugins"

2024-01-01 open Assets:Bank:Erhverv         DKK
2024-01-01 open Assets:Moms:Koebs           DKK
2024-01-01 open Assets:Debitorer            DKK
2024-01-01 open Liabilities:Moms:Salgs      DKK
2024-01-01 open Expenses:Food               DKK
2024-01-01 open Expenses:Personnel:Mileage  DKK
2024-01-01 open Income:Salg:Momspligtigt    DKK

; 1. Custom Expense Standard (100 DKK + 25 VAT)
2024-02-01 custom "quick-expense" Expenses:Food "Lunch" 125.00 DKK "standard"

; 2. Custom Expense Restaurant (1000 DKK incl VAT. VAT=200. Deductible=50. Exp=950)
2024-02-02 custom "quick-expense" Expenses:Food "Dinner" 1000.00 DKK "restaurant"

; 3. Mileage 2025 (100 km @ 3.80)
2025-03-01 custom "quick-mileage" 100 KM

; 4. Sales Invoice
; 10 hrs * 1000 = 10000. VAT 2500. Total 12500.
2024-04-01 custom "sales-invoice" "Acme" "INV-TEST-001" "Income:Salg:Momspligtigt" "Consulting;10;1000"
"""


def verify():
    print("Loading test content...")
    entries, errors, options = loader.load_string(TEST_CONTENT)

    if errors:
        print("ERRORS found during loading:")
        for e in errors:
            print(e)
        # We might have errors if accounts are missing? I defined them.
        # Let's see.

    print(f"Loaded {len(entries)} entries.")

    # Analyze Entries
    transactions = [e for e in entries if isinstance(e, data.Transaction)]
    print(f"Found {len(transactions)} transactions generated from plugins.")

    # 1. Verify Standard Expense
    t1 = next((t for t in transactions if t.narration == "Lunch"), None)
    if t1:
        print("[Pass] Found Standard Expense Transaction")
        # Check amounts
        # Bank should be -125
        # Tax should be 25
        # Expense should be 100
        postings = {p.account: p.units.number for p in t1.postings}
        assert postings["Assets:Bank:Erhverv"] == -125
        assert postings["Assets:Moms:Koebs"] == 25
        assert postings["Expenses:Food"] == 100
        print("   [Pass] Amounts correct")
    else:
        print("[FAIL] Standard Expense logic failed")

    # 2. Verify Restaurant Expense
    t2 = next((t for t in transactions if t.narration == "Dinner"), None)
    if t2:
        print("[Pass] Found Restaurant Expense Transaction")
        # Bank: -1000
        # Tax: 50 (200 * 0.25)
        # Expense: 950 (1000 - 50)
        postings = {p.account: p.units.number for p in t2.postings}
        assert postings["Assets:Bank:Erhverv"] == -1000
        assert postings["Assets:Moms:Koebs"] == 50
        assert postings["Expenses:Food"] == 950
        print("   [Pass] Amounts correct")
    else:
        print("[FAIL] Restaurant Expense logic failed")

    # 3. Verify Mileage
    t3 = next((t for t in transactions if "Mileage:" in t.narration), None)
    if t3:
        print("[Pass] Found Mileage Transaction")
        # 100 * 3.80 = 380
        postings = {p.account: p.units.number for p in t3.postings}
        assert postings["Expenses:Personnel:Mileage"] == 380
        print("   [Pass] Amounts correct")
    else:
        print("[FAIL] Mileage logic failed")

    # 4. Verify Invoice
    t4 = next((t for t in transactions if "Invoice INV-TEST-001" in t.narration), None)
    if t4:
        print("[Pass] Found Invoice Transaction")
        # Net: 10000. VAT: 2500. Gross: 12500.
        postings = {p.account: p.units.number for p in t4.postings}
        assert postings["Assets:Debitorer"] == 12500
        assert postings["Liabilities:Moms:Salgs"] == -2500
        assert postings["Income:Salg:Momspligtigt"] == -10000
        print("   [Pass] Amounts correct")

        # Check PDF
        pdf_path = t4.meta.get("filename")
        if pdf_path and os.path.exists(pdf_path):
            print(f"   [Pass] PDF generated at {pdf_path}")
        else:
            print(f"   [WARN] PDF not found or path missing: {pdf_path}")
            # This might fail if weasyprint missing, but expected behavior is fallback.
    else:
        print("[FAIL] Invoice logic failed")


if __name__ == "__main__":
    verify()
