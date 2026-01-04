import decimal
import getpass
import datetime
from beancount.core import data
from beancount.core import amount

D = decimal.Decimal


def quick_expense(entries, options_map):
    """
    Syntax:
    custom "quick-expense" <ExpenseAccount> <Description> <Amount> <Type>

    Type: "standard" (25% VAT), "restaurant" (25% deduction of VAT), "momsfri" (0% VAT)
    """
    new_entries = []
    errors = []

    for entry in entries:
        if isinstance(entry, data.Custom) and entry.type == "quick-expense":
            # Parsing arguments
            # Expected: account, description, amount, type
            if len(entry.values) != 4:
                errors.append(
                    data.NewError(
                        entry.meta, "Expected 4 arguments for quick-expense", None
                    )
                )
                continue

            expense_account = entry.values[0].value
            description = entry.values[1].value
            total_amount = entry.values[2]  # Amount object
            vat_type = entry.values[3].value

            if not isinstance(total_amount, amount.Amount):
                errors.append(
                    data.NewError(entry.meta, "Third argument must be an amount", None)
                )
                continue

            txn_amount = total_amount.number
            currency = total_amount.currency

            # VAT Logic
            vat_account = "Assets:Moms:Koebs"
            bank_account = "Assets:Bank:Erhverv"

            expense_posting_amount = txn_amount
            vat_posting_amount = D(0)

            if vat_type == "standard":
                # Reverse calculate 25% VAT.
                # Total = Net * 1.25  => Net = Total / 1.25. VAT = Total - Net.
                net_amount = txn_amount / D("1.25")
                vat_posting_amount = txn_amount - net_amount
                expense_posting_amount = net_amount

            elif vat_type == "restaurant":
                # Total = 1000. VAT included = 200.
                # Deductible VAT = 200 * 0.25 = 50.
                # Expense = 1000 - 50 = 950.

                # Full VAT
                net_amount = txn_amount / D("1.25")
                full_vat = txn_amount - net_amount

                # Deductible part
                deductible_vat = full_vat * D("0.25")

                vat_posting_amount = deductible_vat
                expense_posting_amount = txn_amount - deductible_vat

            elif vat_type == "momsfri":
                vat_posting_amount = D(0)
                expense_posting_amount = txn_amount
            else:
                errors.append(
                    data.NewError(entry.meta, f"Unknown VAT type: {vat_type}", None)
                )
                continue

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

            # 2. VAT (if any)
            if vat_posting_amount > 0:
                postings.append(
                    data.Posting(
                        vat_account,
                        amount.Amount(vat_posting_amount, currency),
                        None,
                        None,
                        None,
                        None,
                    )
                )

            # 3. Bank (Negative total)
            postings.append(
                data.Posting(
                    bank_account,
                    amount.Amount(-txn_amount, currency),
                    None,
                    None,
                    None,
                    None,
                )
            )

            # Create Transaction
            # Copy specific meta tags if needed, or just standard ones
            meta = entry.meta

            txn = data.Transaction(
                meta,
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
                    data.NewError(
                        entry.meta,
                        "Expected 1 argument for quick-mileage (Distance)",
                        None,
                    )
                )
                continue

            # Expecting Amount with unit 'KM' presumably, or just a number?
            # Blueprint says "custom 'quick-mileage' ... Output: Beregn udbetaling og generer metadata".
            # The tool call above implied just processing `custom`.
            # Often users write `100 KM`.

            dist_obj = entry.values[0]
            if not isinstance(dist_obj, amount.Amount):
                errors.append(
                    data.NewError(
                        entry.meta, "Argument must be an amount (e.g. 100 KM)", None
                    )
                )
                continue

            dist = dist_obj.number

            year = entry.date.year
            rate = RATES.get(year)
            if not rate:
                errors.append(
                    data.NewError(
                        entry.meta, f"No mileage rate found for year {year}", None
                    )
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
            # Assuming paid out from Bank directly or credited to Owner.
            # Blueprint doesn't specify Account but says "Beregn udbetaling".
            # I will assume "Assets:Bank:Erhverv" for payout to keep it simple, or "Equity:Owner".
            # Let's use Bank as if it was reimbursed immediately.
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
    # datetime already imported at the top

    # Get current user and timestamp for metadata
    try:
        current_user = getpass.getuser()
    except Exception:
        current_user = "Unknown"

    generation_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Path setup
    # Assuming running from project root or finding templates via relative path
    # We will assume CWD is the project root for simplicity in this plugin implementation
    TEMPLATE_DIR = "templates"
    OUTPUT_DIR = "bilag/salg"

    for entry in entries:
        if isinstance(entry, data.Custom) and entry.type == "sales-invoice":
            if len(entry.values) < 4:
                errors.append(
                    data.NewError(
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
                        data.NewError(
                            entry.meta, f"Line item must be string: {item_str}", None
                        )
                    )
                    continue

                parts = item_str.value.split(";")
                if len(parts) != 3:
                    errors.append(
                        data.NewError(
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
                        data.NewError(
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
                            data.NewError(
                                entry.meta, f"Failed to generate PDF: {e}", None
                            )
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
