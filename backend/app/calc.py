"""BLUECARBON ARENA deterministic carbon calculation engine.

EXPLICITLY ILLUSTRATIVE MODEL — NOT AN ACCREDITED METHODOLOGY.
See docs/CARBON_METHODOLOGY.md for assumptions and limitations.

Design rules:
- Pure, deterministic, versioned function (same inputs -> same outputs).
- Decimal arithmetic with fixed quantization (no float drift).
- Rejects missing/invalid/out-of-range inputs with ValueError (structured 400s upstream).
- Never invents official emission factors: coefficients below are clearly-labelled
  illustrative defaults, configurable per run via the API.
- C -> CO2 conversion uses the molecular-weight ratio 44/12.
"""
from decimal import Decimal, ROUND_HALF_UP

METHOD_VERSION = "BCA-ILLUSTRATIVE v1.0"
CO2_OVER_C = Decimal("44") / Decimal("12")  # molecular weight ratio for tC -> tCO2e

# Illustrative average sequestration rates in tC/ha/yr. NOT official factors.
RATES = {
    "mangrove": Decimal("6.0"),
    "tidal_marsh": Decimal("4.5"),
    "seagrass": Decimal("2.5"),
}

QUANT = Decimal("0.0001")


def calculate(area_ha: Decimal, ecosystem: str, years: int,
              uncertainty: Decimal = Decimal("0.10"),
              baseline_tco2e: Decimal = Decimal("0")) -> dict:
    """Return a deterministic calculation result with full audit trail.

    Units: area_ha hectares; gross/net in tCO2e over the reporting period.
    """
    if area_ha is None or area_ha <= 0:
        raise ValueError("area_ha is required and must be positive")
    if years is None or years <= 0 or years > 100:
        raise ValueError("reporting period must be between 1 and 100 years")
    if ecosystem not in RATES:
        raise ValueError(f"unsupported ecosystem: {ecosystem}. "
                         f"Allowed: {', '.join(sorted(RATES))}")
    if uncertainty < 0 or uncertainty >= 1:
        raise ValueError("uncertainty deduction must be in [0, 1)")
    if baseline_tco2e < 0:
        raise ValueError("baseline_tco2e cannot be negative")

    rate = RATES[ecosystem]
    warnings = []

    gross = (Decimal(str(area_ha)) * rate * Decimal(years) * CO2_OVER_C).quantize(
        QUANT, rounding=ROUND_HALF_UP)
    net = (gross * (Decimal("1") - Decimal(str(uncertainty))) - Decimal(str(baseline_tco2e))).quantize(
        QUANT, rounding=ROUND_HALF_UP)
    if net < 0:
        warnings.append("Net eligible removals floored at zero (deductions exceeded gross estimate).")
        net = Decimal("0")

    steps = [
        f"Gross = {area_ha} ha x {rate} tC/ha/yr (illustrative default) x {years} yr x 44/12 = {gross} tCO2e",
        f"Net = Gross x (1 - uncertainty {uncertainty}) - baseline {baseline_tco2e} = {net} tCO2e",
        "Units: tCO2e over the whole reporting period. 1 demo credit = 1 tCO2e of *potential* estimated removals.",
        "Potential != verified. Issuance requires an approved project plus authorized reviewer action.",
    ]
    warnings.append(
        "Illustrative methodology BCA-ILLUSTRATIVE v1.0 — not an accredited blue-carbon methodology. "
        "Coefficients are configurable demonstration defaults, not official emission factors. "
        "Results are estimates, not verified quantities or credits.")
    if uncertainty == 0:
        warnings.append("Uncertainty deduction set to zero; real methodologies require quantified uncertainty.")

    return {
        "methodology_version": METHOD_VERSION,
        "gross_tco2e": float(gross),
        "result_tco2e": float(net),          # net eligible estimated removals (tCO2e)
        "rate_tc_ha_yr": float(rate),
        "steps": steps,
        "warnings": warnings,
    }
