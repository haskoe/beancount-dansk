import sys

try:
    import beancount
    import fava
    import beangulp
    import jinja2
    import weasyprint

    print("SUCCESS: All modules imported successfully.")
except ImportError as e:
    print(f"ERROR: Failed to import module: {e}")
    sys.exit(1)
