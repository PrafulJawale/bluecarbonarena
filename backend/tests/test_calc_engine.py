"""Domain-logic tests for the deterministic carbon calculation engine.

Covers: arithmetic, C->CO2 unit conversion (44/12), precision/rounding,
invalid inputs, missing parameters, reproducibility/determinism.
"""
import pytest
from decimal import Decimal

from app.calc import calculate, METHOD_VERSION, CO2_OVER_C


def test_known_arithmetic_mangrove():
    # 100 ha * 6 tC/ha/yr * 1 yr * 44/12 = 2200 tCO2e gross; *0.9 => 1980 net
    r = calculate(Decimal("100"), "mangrove", 1)
    assert r["gross_tco2e"] == 2200.0
    assert r["result_tco2e"] == 1980.0
    assert r["methodology_version"] == METHOD_VERSION


def test_co2_conversion_ratio_is_44_12():
    # seagrass rate 2.5: 10 ha * 2.5 * 1 yr * 44/12 = 91.6667 tCO2e gross
    r = calculate(Decimal("10"), "seagrass", 1, uncertainty=Decimal("0"))
    assert abs(r["gross_tco2e"] - 91.6667) < 0.001
    assert CO2_OVER_C == Decimal("44") / Decimal("12")


def test_uncertainty_and_baseline_deduction():
    # gross 2200, uncertainty 0.10 -> 1980, baseline 300 -> 1680
    r = calculate(Decimal("100"), "mangrove", 1,
                  uncertainty=Decimal("0.10"), baseline_tco2e=Decimal("300"))
    assert r["result_tco2e"] == 1680.0


def test_net_floor_at_zero():
    r = calculate(Decimal("10"), "mangrove", 1,
                  uncertainty=Decimal("0.5"), baseline_tco2e=Decimal("100000"))
    assert r["result_tco2e"] == 0.0
    assert any("floor" in w.lower() or "zero" in w.lower() for w in r["warnings"])


def test_precision_four_decimals_rounding():
    r = calculate(Decimal("33.3333"), "tidal_marsh", 7, uncertainty=Decimal("0.123"))
    q = str(r["result_tco2e"]).split(".")[-1]
    assert len(q) <= 4


def test_invalid_area_rejected():
    with pytest.raises(ValueError):
        calculate(Decimal("0"), "mangrove", 1)
    with pytest.raises(ValueError):
        calculate(Decimal("-5"), "mangrove", 1)


def test_invalid_period_rejected():
    with pytest.raises(ValueError):
        calculate(Decimal("10"), "mangrove", 0)
    with pytest.raises(ValueError):
        calculate(Decimal("10"), "mangrove", 101)


def test_unsupported_ecosystem_rejected():
    with pytest.raises(ValueError):
        calculate(Decimal("10"), "coral_reef", 1)


def test_uncertainty_out_of_range_rejected():
    with pytest.raises(ValueError):
        calculate(Decimal("10"), "mangrove", 1, uncertainty=Decimal("1"))
    with pytest.raises(ValueError):
        calculate(Decimal("10"), "mangrove", 1, uncertainty=Decimal("-0.1"))


def test_negative_baseline_rejected():
    with pytest.raises(ValueError):
        calculate(Decimal("10"), "mangrove", 1, baseline_tco2e=Decimal("-1"))


def test_deterministic_reproducible():
    a = calculate(Decimal("120.5"), "mangrove", 5,
                  uncertainty=Decimal("0.1"), baseline_tco2e=Decimal("10"))
    b = calculate(Decimal("120.5"), "mangrove", 5,
                  uncertainty=Decimal("0.1"), baseline_tco2e=Decimal("10"))
    assert a == b  # identical inputs -> identical outputs incl. steps/warnings


def test_steps_document_formula_and_units():
    r = calculate(Decimal("10"), "mangrove", 1)
    joined = " ".join(r["steps"])
    assert "ha" in joined and "tCO2e" in joined and "44/12" in joined
    assert any("illustrative" in w.lower() for w in r["warnings"])
