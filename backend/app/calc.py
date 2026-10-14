
from decimal import Decimal,ROUND_HALF_UP
RATES={"mangrove":Decimal("6.0"),"tidal_marsh":Decimal("4.5"),"seagrass":Decimal("2.5")} # illustrative tC/ha/yr, NOT official factors
def calculate(area_ha,ecosystem,years,uncertainty=Decimal("0.10"),baseline_tco2e=Decimal("0")):
    if area_ha<=0: raise ValueError("area_ha must be positive")
    if years<=0 or years>100: raise ValueError("reporting period must be 1-100 years")
    if ecosystem not in RATES: raise ValueError(f"unsupported ecosystem: {ecosystem}")
    if uncertainty<0 or uncertainty>=1: raise ValueError("uncertainty must be in [0,1)")
    rate=RATES[ecosystem]; co2=Decimal("44")/Decimal("12")
    gross=(area_ha*rate*Decimal(years)*co2).quantize(Decimal("0.0001"),rounding=ROUND_HALF_UP)
    net=(gross*(Decimal("1")-uncertainty)-baseline_tco2e).quantize(Decimal("0.0001"),rounding=ROUND_HALF_UP)
    if net<0: net=Decimal("0")
    steps=[f"Gross = {area_ha} ha x {rate} tC/ha/yr (illustrative) x {years} yr x 44/12 = {gross} tCO2e",f"Net = Gross x (1-{uncertainty}) - baseline {baseline_tco2e} = {net} tCO2e","1 credit in this demo corresponds to 1 tCO2e of *potential* estimated removals; issuance requires approval."]
    return {"gross_tco2e":float(gross),"result_tco2e":float(net),"rate_tc_ha_yr":float(rate),"steps":steps,"warnings":["Illustrative methodology BCA-ILLUSTRATIVE v1.0 - not an accredited methodology. Results are estimates, not verified credits."]}
