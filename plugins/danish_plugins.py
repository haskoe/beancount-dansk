import decimal
import datetime
import getpass
import os
from collections import namedtuple
from beancount.core import data
from beancount.core import amount

D = decimal.Decimal
Error = namedtuple("Error", "source message entry")


def get_auto_link(date, account):
    """Generate YYMMDD-AccountName link."""
    date_str = date.strftime("%y%m%d")
    safe_acc = account.replace(":", "-")
    return f"{date_str}-{safe_acc}"


def quick_expense(entries, options_map):
    """
    Legacy Syntax (keeping for compatibility):
    custom "quick-expense" <ExpenseAccount> <Description> <Amount> <Type> [CreditAccount] [InvoiceRef] [NetAmount]
    """
    new_entries = []
    errors = []

    for entry in entries:
        is_legacy = isinstance(entry, data.Custom) and entry.type == "quick-expense"
        is_short = isinstance(entry, data.Custom) and entry.type == "u"

        if is_legacy or is_short:
            if is_legacy:
                if len(entry.values) < 4 or len(entry.values) > 7:
                    errors.append(
                        Error(
                            entry.meta,
                            "Expected 4 to 7 arguments for quick-expense",
                            None,
                        )
                    )
                    continue
                expense_account = entry.values[0].value
                description = entry.values[1].value
                total_amount_wrapper = entry.values[2]
                vat_type_arg = entry.values[3].value
            else:  # is_short
                if len(entry.values) != 3:
                    errors.append(
                        Error(
                            entry.meta,
                            "Expected 3 arguments for 'u' one-liner (Account, Description, Amount)",
                            None,
                        )
                    )
                    continue
                expense_account = entry.values[0].value
                description = entry.values[1].value
                total_amount_wrapper = entry.values[2]
                vat_type_arg = None  # Will infer from filename

            # Detect VAT type from filename if not provided in args
            vat_type = vat_type_arg
            if not vat_type and "filename" in entry.meta:
                fname = entry.meta["filename"]
                if "expenses_moms.beancount" in fname:
                    vat_type = "standard"
                elif "expenses_momsfri.beancount" in fname:
                    vat_type = "momsfri"
                elif "expenses_udland.beancount" in fname:
                    vat_type = "u-moms"
                elif "expenses_repraesentation.beancount" in fname:
                    vat_type = "restaurant"

            if not vat_type:
                vat_type = "momsfri"  # Fallback

            credit_account = entry.meta.get("credit", "Assets:Bank:Erhverv")
            if credit_account == "Kreditorer":
                credit_account = "Liabilities:Kreditorer"
            if is_legacy and len(entry.values) >= 5:
                credit_account = entry.values[4].value

            invoice_ref = entry.meta.get("invoice")
            if is_legacy and not invoice_ref and len(entry.values) >= 6:
                invoice_ref = entry.values[5].value

            net_amount_hint = None
            if is_legacy and len(entry.values) == 7:
                net_amount_hint = entry.values[6].value

            total_amount = total_amount_wrapper.value
            if not isinstance(total_amount, amount.Amount):
                errors.append(
                    Error(entry.meta, "Third argument must be an amount", None)
                )
                continue

            txn_amount = total_amount.number
            currency = total_amount.currency

            vat_buy_account = "Assets:Moms:Koeb"
            vat_sell_account = "Liabilities:Moms:Salg"

            expense_posting_amount = txn_amount
            vat_buy_posting_amount = D(0)
            vat_sell_posting_amount = D(0)

            if vat_type == "standard":
                net_amount = txn_amount / D("1.25")
                vat_buy_posting_amount = txn_amount - net_amount
                expense_posting_amount = net_amount
            elif vat_type == "restaurant":
                net_amount = txn_amount / D("1.25")
                full_vat = txn_amount - net_amount
                deductible_vat = full_vat * D("0.25")
                vat_buy_posting_amount = deductible_vat
                expense_posting_amount = txn_amount - deductible_vat
            elif vat_type == "u-moms":
                expense_posting_amount = txn_amount
                vat_buy_posting_amount = txn_amount * D("0.25")
                vat_sell_posting_amount = -vat_buy_posting_amount
            elif vat_type == "momsfri":
                pass
            else:
                errors.append(Error(entry.meta, f"Unknown VAT type: {vat_type}", None))
                continue

            if net_amount_hint and abs(
                net_amount_hint.number - expense_posting_amount
            ) > D("0.05"):
                errors.append(
                    Error(
                        entry.meta,
                        f"Net amount verification failed. Calc: {expense_posting_amount}, Hint: {net_amount_hint.number}",
                        None,
                    )
                )

            postings = [
                data.Posting(
                    expense_account,
                    amount.Amount(expense_posting_amount, currency),
                    None,
                    None,
                    None,
                    None,
                )
            ]
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

            links = {get_auto_link(entry.date, expense_account)}
            meta = entry.meta.copy()
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


def auto_fill_expenses(entries, options_map):
    """
    Automatically fills in VAT and balancing postings for transactions in typed expense files.
    """
    new_entries = []
    errors = []

    vat_buy_account = "Assets:Moms:Koeb"
    vat_sell_account = "Liabilities:Moms:Salg"

    for entry in entries:
        if isinstance(entry, data.Transaction) and "filename" in entry.meta:
            filename = entry.meta["filename"]

            # Detect VAT type from filename
            vat_type = None
            if "expenses_moms.beancount" in filename:
                vat_type = "standard"
            elif "expenses_momsfri.beancount" in filename:
                vat_type = "momsfri"
            elif "expenses_udland.beancount" in filename:
                vat_type = "u-moms"
            elif "expenses_repraesentation.beancount" in filename:
                vat_type = "restaurant"

            if vat_type and len(entry.postings) == 1:
                p = entry.postings[0]
                expense_account = p.account
                txn_amount = p.units.number
                currency = p.units.currency

                expense_posting_amount = txn_amount
                vat_buy_posting_amount = D(0)
                vat_sell_posting_amount = D(0)

                if vat_type == "standard":
                    net_amount = txn_amount / D("1.25")
                    vat_buy_posting_amount = txn_amount - net_amount
                    expense_posting_amount = net_amount
                elif vat_type == "restaurant":
                    net_amount = txn_amount / D("1.25")
                    full_vat = txn_amount - net_amount
                    deductible_vat = full_vat * D("0.25")
                    vat_buy_posting_amount = deductible_vat
                    expense_posting_amount = txn_amount - deductible_vat
                elif vat_type == "u-moms":
                    expense_posting_amount = txn_amount
                    vat_buy_posting_amount = txn_amount * D("0.25")
                    vat_sell_posting_amount = -vat_buy_posting_amount

                # Update first posting
                new_postings = [
                    data.Posting(
                        expense_account,
                        amount.Amount(expense_posting_amount, currency),
                        None,
                        None,
                        None,
                        None,
                    )
                ]

                # Add VAT postings
                if vat_buy_posting_amount != 0:
                    new_postings.append(
                        data.Posting(
                            vat_buy_account,
                            amount.Amount(vat_buy_posting_amount, currency),
                            None,
                            None,
                            None,
                            None,
                        )
                    )
                if vat_sell_posting_amount != 0:
                    new_postings.append(
                        data.Posting(
                            vat_sell_account,
                            amount.Amount(vat_sell_posting_amount, currency),
                            None,
                            None,
                            None,
                            None,
                        )
                    )

                # Add Balancing Posting
                credit_account = entry.meta.get("credit", "Assets:Bank:Erhverv")
                if credit_account == "Kreditorer":
                    credit_account = "Liabilities:Kreditorer"  # Shortcut
                new_postings.append(
                    data.Posting(
                        credit_account,
                        amount.Amount(-txn_amount, currency),
                        None,
                        None,
                        None,
                        None,
                    )
                )

                # Links
                links = set(entry.links) if entry.links else set()
                links.add(get_auto_link(entry.date, expense_account))
                if "invoice" in entry.meta:
                    links.add(entry.meta["invoice"])

                new_txn = entry._replace(postings=new_postings, links=links)
                new_entries.append(new_txn)
                continue

        new_entries.append(entry)

    return new_entries, errors


def quick_mileage(entries, options_map):
    new_entries = []
    errors = []
    RATES = {2025: D("3.80"), 2026: D("3.82")}
    for entry in entries:
        if isinstance(entry, data.Custom) and entry.type == "quick-mileage":
            if len(entry.values) != 1:
                errors.append(
                    Error(entry.meta, "Expected 1 argument for quick-mileage", None)
                )
                continue
            dist_wrapper = entry.values[0]
            dist_obj = dist_wrapper.value
            if not isinstance(dist_obj, amount.Amount):
                errors.append(Error(entry.meta, "Argument must be an amount", None))
                continue
            dist = dist_obj.number
            year = entry.date.year
            rate = RATES.get(year)
            if not rate:
                errors.append(
                    Error(entry.meta, f"No mileage rate found for year {year}", None)
                )
                continue
            payout = (dist * rate).quantize(D("0.01"))
            description = f"Mileage: {dist} km @ {rate} DKK/km"
            postings = [
                data.Posting(
                    "Expenses:Personnel:Mileage",
                    amount.Amount(payout, "DKK"),
                    None,
                    None,
                    None,
                    None,
                ),
                data.Posting(
                    "Assets:Bank:Erhverv",
                    amount.Amount(-payout, "DKK"),
                    None,
                    None,
                    None,
                    None,
                ),
            ]
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
    new_entries = []
    errors = []
    try:
        from jinja2 import Environment, FileSystemLoader
        import weasyprint

        HAS_PDF_DEPS = True
    except ImportError:
        HAS_PDF_DEPS = False

    generation_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    TEMPLATE_DIR = "templates"
    OUTPUT_DIR = "bilag/salg"

    for entry in entries:
        if isinstance(entry, data.Custom) and entry.type == "sales-invoice":
            if len(entry.values) < 4:
                errors.append(Error(entry.meta, "Expected at least 4 arguments", None))
                continue
            client_name = entry.values[0].value
            invoice_id = entry.values[1].value
            income_account = entry.values[2].value
            line_item_strs = entry.values[3:]
            items = []
            total_net = D(0)
            for item_str in line_item_strs:
                parts = item_str.value.split(";")
                if len(parts) != 3:
                    continue
                qty, price = D(parts[1]), D(parts[2])
                line_total = qty * price
                items.append(
                    {
                        "desc": parts[0],
                        "qty": qty,
                        "price": price,
                        "line_total": line_total,
                    }
                )
                total_net += line_total
            vat_amount = total_net * D("0.25")
            total_gross = total_net + vat_amount
            date = entry.date
            due_date = date + datetime.timedelta(days=14)
            meta = entry.meta.copy()
            meta["due_date"] = due_date.isoformat()
            if HAS_PDF_DEPS:
                filepath = os.path.join(OUTPUT_DIR, f"{invoice_id}.pdf")
                meta["filename"] = os.path.abspath(filepath)
                if not os.path.exists(filepath):
                    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
                    template = env.get_template("invoice.html")
                    html_out = template.render(
                        invoice_id=invoice_id,
                        date=date.strftime("%Y-%m-%d"),
                        due_date=due_date.strftime("%Y-%m-%d"),
                        client_name=client_name,
                        items=items,
                        total_net=total_net,
                        total_vat=vat_amount,
                        total_gross=total_gross,
                        metadata={
                            "generated_at": generation_time,
                            "generated_by": getpass.getuser(),
                            "company_name": "Min Virksomhed ApS",
                            "invoice_id": invoice_id,
                        },
                    )
                    weasyprint.HTML(string=html_out).write_pdf(filepath)
            postings = [
                data.Posting(
                    "Assets:Debitorer",
                    amount.Amount(total_gross, "DKK"),
                    None,
                    None,
                    None,
                    None,
                ),
                data.Posting(
                    income_account,
                    amount.Amount(-total_net, "DKK"),
                    None,
                    None,
                    None,
                    None,
                ),
                data.Posting(
                    "Liabilities:Moms:Salg",
                    amount.Amount(-vat_amount, "DKK"),
                    None,
                    None,
                    None,
                    None,
                ),
            ]
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


__plugins__ = [quick_expense, auto_fill_expenses, quick_mileage, sales_invoice]
