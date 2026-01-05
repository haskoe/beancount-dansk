# Beancount Danmark

Et modulært Beancount-økosystem skræddersyet til danske virksomhedsregler, herunder moms-automatisering, kørselsgodtgørelse og fakturering.

## 1. Introduktion
Dette system er bygget til at forenkle bogføring for danske selvstændige og mindre virksomheder ved hjælp af Plain Text Accounting (Beancount). Det inkluderer specialiserede plugins til at håndtere danske særregler som repræsentationsmoms og statens takster for kørsel.

## 2. Installation & Opsætning
Systemet bruger `uv` til pakkehåndtering.

### Forudsætninger
Sørg for at have `uv` installeret. Hvis ikke, se [docs.astral.sh/uv](https://docs.astral.sh/uv/).

### Opsætning
Kør installationsscriptet for at klargøre miljøet og installere afhængigheder (`beancount`, `fava`, `weasyprint`, etc.):

```bash
chmod +x install.sh
./install.sh
```

## 3. Mappestruktur & Organisering
Projektet er organiseret efter årstal for at holde transaktionerne overskuelige.

-   `20XX/`
    -   `expenses_moms.beancount`: Udgifter med moms.
    -   `expenses_momsfri.beancount`: Udgifter uden moms.
    -   `expenses_udland.beancount`: Udenlandske køb (u-moms).
    -   `expenses_repraesentation.beancount`: Repræsentation.
    -   `mileage.beancount`: Kørselsregnskab.
    -   `invoices.beancount`: Salgsfakturaer.

### Opret nyt år
Brug scriptet `new_year.sh` til at oprette en ny årsfolder med de nødvendige filer:

```bash
chmod +x new_year.sh
./new_year.sh 2026
```

## 4. Eksempler på Custom Posteringer
Disse bør placeres i de relevante filer i årsfolderne (f.eks. `2025/expenses.beancount`).

### Fava (Web Interface)
For at starte det visuelle dashboard:
```bash
uv run fava regnskab.beancount
# Eller hvis du får ModuleNotFoundError:
PYTHONPATH=. uv run fava regnskab.beancount
```

### Queries (Terminal)
Systemet indeholder præ-definerede queries til moms og ubetalte fakturaer.

```bash
# Moms-oversigt
PYTHONPATH=. uv run bean-query regnskab.beancount ".run moms-oversigt"

# Forfaldne fakturaer
PYTHONPATH=. uv run bean-query regnskab.beancount ".run forfaldne-fakturaer"
```

---
*Vedligeholdt af: Senior Arkitekt for Dansk Bogføring*
