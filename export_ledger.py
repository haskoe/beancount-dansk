import sys
import os
from beancount import loader
from beancount.parser import printer


def export_ledger(input_file, output_file):
    print(f"Loading {input_file}...")
    # Ensure local plugins can be found
    sys.path.insert(0, os.getcwd())

    entries, errors, options = loader.load_file(input_file)

    if errors:
        print(f"Found {len(errors)} errors during loading:")
        for error in errors:
            print(error)
        print("\nProceeding with export despite errors...\n")

    print(f"Exporting {len(entries)} entries to {output_file}...")
    with open(output_file, "w") as f:
        # Print options first for a valid beancount file
        for key, value in sorted(options.items()):
            if isinstance(value, (str, int, float)) and key not in [
                "filename",
                "include",
            ]:
                f.write(f'option "{key}" "{value}"\n')
        f.write("\n")

        # Print entries
        printer.print_entries(entries, file=f)

    print("Done.")


if __name__ == "__main__":
    INPUT = "regnskab.beancount"
    OUTPUT = "regnskab_genereret.beancount"
    export_ledger(INPUT, OUTPUT)
