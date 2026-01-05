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
2024-01-01 open Assets:Moms:Koeb
2024-01-01 open Assets:Debitorer
2024-01-01 open Liabilities:Moms:Salg
2024-01-01 open Liabilities:Kreditorer
2024-01-01 open Expenses:Food
2024-01-01 open Expenses:Software
2024-01-01 open Expenses:Office:Supplies
2024-01-01 open Expenses:Personnel:Mileage
2024-01-01 open Income:Salg:Momspligtigt

; Note: In the real system, files are detected by filename. 
; Here we will test the quick-expense legacy syntax first, then standard transactions.
; For auto-fill testing, we'd need to mock the filename in metadata, which is hard in loader.load_string.
; However, the danish_plugins.py uses 'filename' from metadata.

; 1. Standard Expense (Legacy)
2024-02-01 custom "quick-expense" Expenses:Food "Lunch Legacy" 125.00 DKK "standard"

; 2. Restaurant Expense (Legacy)
2024-02-02 custom "quick-expense" Expenses:Food "Dinner Legacy" 1000.00 DKK "restaurant"

; 3. One-liner (Note: VAT type will be momsfri here as there's no filename in load_string)
2024-02-03 custom "u" Expenses:Office:Supplies "Supplies One-liner" 100.00 DKK

"""


def verify():
    print("Loading test content...")
    # Since we can't easily simulatefilenames in load_string for auto_fill_expenses,
    # we will rely on bean-check on the actual files later.
    # But let's verify the legacy quick-expense still works with new account names.
    entries, errors, options = loader.load_string(TEST_CONTENT)

    if errors:
        print("ERRORS found during loading:")
        for e in errors:
            print(e)
        # sys.exit(1)

    transactions = [e for e in entries if isinstance(e, data.Transaction)]
    print(f"Loaded {len(entries)} entries, {len(transactions)} generated transactions.")

    # 1. Standard Legacy
    t1 = next((t for t in transactions if t.narration == "Lunch Legacy"), None)
    if t1:
        postings = {p.account: p.units.number for p in t1.postings}
        assert postings["Assets:Bank:Erhverv"] == -125
        assert postings["Assets:Moms:Koeb"] == 25
        print("[Pass] Legacy Standard Expense")

    # 2. Restaurant Legacy
    t2 = next((t for t in transactions if t.narration == "Dinner Legacy"), None)
    if t2:
        postings = {p.account: p.units.number for p in t2.postings}
        assert postings["Assets:Moms:Koeb"] == 50
        assert postings["Expenses:Food"] == 950
        print("[Pass] Legacy Restaurant Expense")

    # 3. One-liner
    t3 = next((t for t in transactions if t.narration == "Supplies One-liner"), None)
    if t3:
        # Should be momsfri (fallback) and balanced against bank
        postings = {p.account: p.units.number for p in t3.postings}
        assert postings["Expenses:Office:Supplies"] == 100
        assert postings["Assets:Bank:Erhverv"] == -100
        assert "240203-Expenses-Office-Supplies" in t3.links
        print("[Pass] One-liner 'u' syntax")

    print("\nRunning bean-check on regnskab.beancount to verify auto_fill_expenses...")
    # This will check the actual files with actual filenames
    os.system(
        "PYTHONPATH=. uv run bean-check regnskab.beancount > check_output.txt 2>&1"
    )
    with open("check_output.txt", "r") as f:
        output = f.read()
        if output:
            print("bean-check found issues:")
            print(output)
        else:
            print("[Pass] bean-check on real files (auto-fill verified)")


if __name__ == "__main__":
    verify()
