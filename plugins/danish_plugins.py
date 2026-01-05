import decimal
import datetime
import getpass
from collections import namedtuple
from beancount.core import data
from beancount.core import amount

D = decimal.Decimal
Error = namedtuple("Error", "source message entry")


def quick_expense(entries, options_map):
    """
    Syntax:
    custom "quick-expense" <ExpenseAccount> <Description> <Amount> <Type> [CreditAccount] [InvoiceRef] [NetAmount]

    Type:
    - "standard" (25% VAT)
    - "restaurant" (25% of VAT is deductible - representation)
    - "momsfri" (0% VAT)
    - "u-moms" (Reverse charge - EU/Foreign. 25% added to both purchase and sales VAT)
    """
    new_entries = []
    errors = []

    for entry in entries:
        if isinstance(entry, data.Custom) and entry.type == "quick-expense":
            # Parsing arguments
            # Expected: account, description, amount, type, [credit_account], [invoice_ref], [net_amount]
            if len(entry.values) < 4 or len(entry.values) > 7:
                errors.append(
                    Error(
                        entry.meta, "Expected 4 to 7 arguments for quick-expense", None
                    )
                )
                continue

            expense_account = entry.values[0].value
            description = entry.values[1].value
            total_amount_wrapper = entry.values[2]  # ValueType
            vat_type = entry.values[3].value

            # Optional arguments
            credit_account = "Assets:Bank:Erhverv"
            if len(entry.values) >= 5:
                credit_account = entry.values[4].value

            invoice_ref = None
            if len(entry.values) >= 6:
                invoice_ref = entry.values[5].value

            net_amount_hint = None
            if len(entry.values) == 7:
                net_amount_hint = entry.values[6].value

            total_amount = total_amount_wrapper.value
            if not isinstance(total_amount, amount.Amount):
                errors.append(
                    Error(entry.meta, "Third argument must be an amount", None)
                )
                continue

            txn_amount = total_amount.number
            currency = total_amount.currency

            # VAT Logic
            vat_buy_account = "Assets:Moms:Koebs"
            vat_sell_account = "Liabilities:Moms:Salgs"

            expense_posting_amount = txn_amount
            vat_buy_posting_amount = D(0)
            vat_sell_posting_amount = D(0)

            if vat_type == "standard":
                # Reverse calculate 25% VAT.
                # Total = Net * 1.25  => Net = Total / 1.25. VAT = Total - Net.
                net_amount = txn_amount / D("1.25")
                vat_buy_posting_amount = txn_amount - net_amount
                expense_posting_amount = net_amount

            elif vat_type == "restaurant":
                # Total = 1000. VAT included = 200.
                # Deductible VAT = 200 * 0.25 = 50.
                # Expense = 1000 - 50 = 950.
                net_amount = txn_amount / D("1.25")
                full_vat = txn_amount - net_amount
                deductible_vat = full_vat * D("0.25")
                vat_buy_posting_amount = deductible_vat
                expense_posting_amount = txn_amount - deductible_vat

            elif vat_type == "u-moms":
                # Reverse charge. Total paid is the Net.
                # VAT is 25% of Net, added to both buy and sell accounts.
                expense_posting_amount = txn_amount
                vat_buy_posting_amount = txn_amount * D("0.25")
                vat_sell_posting_amount = -vat_buy_posting_amount

            elif vat_type == "momsfri":
                vat_buy_posting_amount = D(0)
                expense_posting_amount = txn_amount
            else:
                errors.append(Error(entry.meta, f"Unknown VAT type: {vat_type}", None))
                continue

            # Verification of NetAmount hint if provided
            if net_amount_hint:
                if not isinstance(net_amount_hint, amount.Amount):
                    errors.append(
                        Error(entry.meta, "7th argument must be an amount", None)
                    )
                elif abs(net_amount_hint.number - expense_posting_amount) > D("0.05"):
                    errors.append(
                        Error(
                            entry.meta,
                            f"Net amount verification failed. Calculated: {expense_posting_amount}, Hint: {net_amount_hint.number}",
                            None,
                        )
                    )

            # Create Postings
            postings = []

            # 1. Expense
            postings.append(
                data.Posting(
                    expense_account,
                    amount.Amount(expense_posting_amount, currency),
                    None,
                    None,
                    None,
                    None,
                )
            )

            # 2. Buy VAT (if any)
            if vat_buy_posting_amount != 0:
                postings.append(
                    data.Posting(
                        vat_buy_account,
                        amount.Amount(vat_buy_posting_amount, currency),
                        None,
                        None,
                        None,
                        None,
                    )
                )

            # 3. Sell VAT (for u-moms)
            if vat_sell_posting_amount != 0:
                postings.append(
                    data.Posting(
                        vat_sell_account,
                        amount.Amount(vat_sell_posting_amount, currency),
                        None,
                        None,
                        None,
                        None,
                    )
                )

            # 4. Credit Account (Negative total payment)
            postings.append(
                data.Posting(
                    credit_account,
                    amount.Amount(-txn_amount, currency),
                    None,
                    None,
                    None,
                    None,
                )
            )

            # Create Transaction
            meta = entry.meta.copy()
            links = set()

            # Automatic Link Generation: YYMMDD-AccountName
            date_str = entry.date.strftime("%y%m%d")
            safe_acc = expense_account.replace(":", "-")
            auto_link = f"{date_str}-{safe_acc}"
            links.add(auto_link)

            if invoice_ref:
                meta["invoice"] = invoice_ref
                links.add(invoice_ref)

            txn = data.Transaction(
                meta,
                entry.date,
                "*",
                None,
                description,
                data.EMPTY_SET,
                links,
                postings,
            )
            new_entries.append(txn)

        else:
            new_entries.append(entry)

    return new_entries, errors


def quick_mileage(entries, options_map):
    """
    Syntax:
    custom "quick-mileage" <Distance>

    Uses date to lookup rate.
    """
    new_entries = []
    errors = []

    RATES = {2025: D("3.80"), 2026: D("3.82")}

    for entry in entries:
        if isinstance(entry, data.Custom) and entry.type == "quick-mileage":
            if len(entry.values) != 1:
                errors.append(
                    Error(
                        entry.meta,
                        "Expected 1 argument for quick-mileage (Distance)",
                        None,
                    )
                )
                continue

            dist_wrapper = entry.values[0]
            dist_obj = dist_wrapper.value
            if not isinstance(dist_obj, amount.Amount):
                errors.append(
                    Error(entry.meta, "Argument must be an amount (e.g. 100 KM)", None)
                )
                continue

            dist = dist_obj.number

            year = entry.date.year
            rate = RATES.get(year)
            if not rate:
                errors.append(
                    Error(entry.meta, f"No mileage rate found for year {year}", None)
                )
                continue

            payout = dist * rate
            payout = payout.quantize(D("0.01"))

            description = f"Mileage: {dist} km @ {rate} DKK/km"

            # Postings
            postings = []

            # Expense
            postings.append(
                data.Posting(
                    "Expenses:Personnel:Mileage",
                    amount.Amount(payout, "DKK"),
                    None,
                    None,
                    None,
                    None,
                )
            )

            # Liability/Payout (Credit Owner/Bank)
            postings.append(
                data.Posting(
                    "Assets:Bank:Erhverv",
                    amount.Amount(-payout, "DKK"),
                    None,
                    None,
                    None,
                    None,
                )
            )

            txn = data.Transaction(
                entry.meta,
                entry.date,
                "*",
                None,
                description,
                data.EMPTY_SET,
                data.EMPTY_SET,
                postings,
            )
            new_entries.append(txn)
        else:
            new_entries.append(entry)

    return new_entries, errors


def sales_invoice(entries, options_map):
    """
    Syntax:
    custom "sales-invoice" <Client> <InvoiceID> <IncomeAccount> <Line1> <Line2> ...

    Line format: "Description;Quantity;Price"
    """
    new_entries = []
    errors = []

    # Try importing optional dependencies
    try:
        from jinja2 import Environment, FileSystemLoader
        import weasyprint

        HAS_PDF_DEPS = True
    except ImportError:
        HAS_PDF_DEPS = False

    import os

    # Get current user and timestamp for metadata
    try:
        current_user = getpass.getuser()
    except Exception:
        current_user = "Unknown"

    generation_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Path setup
    TEMPLATE_DIR = "templates"
    OUTPUT_DIR = "bilag/salg"

    for entry in entries:
        if isinstance(entry, data.Custom) and entry.type == "sales-invoice":
            if len(entry.values) < 4:
                errors.append(
                    Error(
                        entry.meta,
                        "Expected at least 4 arguments for sales-invoice",
                        None,
                    )
                )
                continue

            client_name = entry.values[0].value
            invoice_id = entry.values[1].value
            income_account = entry.values[2].value
            line_item_strs = entry.values[3:]

            items = []
            total_net = D(0)

            for item_str in line_item_strs:
                if not isinstance(item_str.value, str):
                    errors.append(
                        Error(entry.meta, f"Line item must be string: {item_str}", None)
                    )
                    continue

                parts = item_str.value.split(";")
                if len(parts) != 3:
                    errors.append(
                        Error(
                            entry.meta,
                            f"Invalid line item format: {item_str.value}. Expected 'Desc;Qty;Price'",
                            None,
                        )
                    )
                    continue

                desc = parts[0]
                try:
                    qty = D(parts[1])
                    price = D(parts[2])
                except (ValueError, decimal.InvalidOperation):
                    errors.append(
                        Error(
                            entry.meta,
                            f"Invalid number in line item: {item_str.value}",
                            None,
                        )
                    )
                    continue

                line_total = qty * price
                items.append(
                    {"desc": desc, "qty": qty, "price": price, "line_total": line_total}
                )
                total_net += line_total

            vat_amount = total_net * D("0.25")
            total_gross = total_net + vat_amount

            # Create Transaction
            date = entry.date
            due_date = date + datetime.timedelta(days=14)
            due_date_str = due_date.strftime("%Y-%m-%d")

            meta = entry.meta.copy()
            meta["due_date"] = due_date.isoformat()

            # PDF Generation
            filename = f"{invoice_id}.pdf"
            if HAS_PDF_DEPS:
                filepath = os.path.join(OUTPUT_DIR, filename)
                meta["filename"] = os.path.abspath(filepath)  # Link in beancount

                if not os.path.exists(filepath):
                    # Render
                    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
                    template = env.get_template("invoice.html")
                    html_out = template.render(
                        invoice_id=invoice_id,
                        date=date.strftime("%Y-%m-%d"),
                        due_date=due_date_str,
                        client_name=client_name,
                        items=items,
                        total_net=total_net,
                        total_vat=vat_amount,
                        total_gross=total_gross,
                        metadata={
                            "generated_at": generation_time,
                            "generated_by": current_user,
                            "company_name": "Min Virksomhed ApS",
                            "invoice_id": invoice_id,
                        },
                    )

                    try:
                        weasyprint.HTML(string=html_out).write_pdf(filepath)
                    except Exception as e:
                        # Don't crash processing, just log error
                        errors.append(
                            Error(entry.meta, f"Failed to generate PDF: {e}", None)
                        )

            postings = []
            # Debit Debitorer (Gross)
            postings.append(
                data.Posting(
                    "Assets:Debitorer",
                    amount.Amount(total_gross, "DKK"),
                    None,
                    None,
                    None,
                    None,
                )
            )

            # Credit Income (Net)
            postings.append(
                data.Posting(
                    income_account,
                    amount.Amount(-total_net, "DKK"),
                    None,
                    None,
                    None,
                    None,
                )
            )

            # Credit VAT (VAT)
            postings.append(
                data.Posting(
                    "Liabilities:Moms:Salgs",
                    amount.Amount(-vat_amount, "DKK"),
                    None,
                    None,
                    None,
                    None,
                )
            )

            txn = data.Transaction(
                meta,
                date,
                "*",
                client_name,
                f"Invoice {invoice_id}",
                data.EMPTY_SET,
                data.EMPTY_SET,
                postings,
            )
            new_entries.append(txn)

        else:
            new_entries.append(entry)

    return new_entries, errors


__plugins__ = [quick_expense, quick_mileage, sales_invoice]
