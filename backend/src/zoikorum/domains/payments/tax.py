"""Invoice tax (Payments & Escrow: tax on invoices; rates are a finance decision, ZK_TAX_RULES).

Amounts on Zoikorum are tax-inclusive, so tax never changes what is funded, released or paid out: the invoice shows the
tax contained in the amount ("of which VAT 20%"). The rule is chosen by the buyer's country: the contracting legal entity
when the contract names one, otherwise the organisation's country.
"""

from __future__ import annotations

from dataclasses import dataclass

from zoikorum.config import get_settings


@dataclass(frozen=True)
class TaxLine:
    label: str
    rate_bps: int
    basis: str  # FEE | TOTAL
    amount_minor: int

    @property
    def description(self) -> str:
        rate = f"{self.rate_bps / 100:g}%"
        on = "on the Zoikorum platform fee" if self.basis == "FEE" else "on the amount"
        return f"Of which {self.label} {rate} {on} (included)"


def included_tax(country: str | None, gross_minor: int, fee_minor: int) -> TaxLine | None:
    rule = get_settings().tax_rules.get((country or "").upper())
    if not rule:
        return None
    rate, basis = int(rule["rateBps"]), str(rule.get("basis", "TOTAL")).upper()
    base = fee_minor if basis == "FEE" else gross_minor
    amount = round(base * rate / (10_000 + rate))  # the tax part of a tax-inclusive amount
    return TaxLine(label=str(rule.get("label", "Tax")), rate_bps=rate, basis=basis, amount_minor=amount)
