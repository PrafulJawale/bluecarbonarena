import os, sys, pathlib
os.environ["DATABASE_URL"]="sqlite:///./test_bca.db"
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from fastapi.testclient import TestClient
from app.main import app
from app.calc import calculate
from decimal import Decimal
import pytest
c=TestClient(app)
def reg(email,role="developer"):
    r=c.post("/api/v1/auth/register",json={"email":email,"password":"Password123!","full_name":"T","role":role}); assert r.status_code==200, r.text; return r.json()["access_token"]
def test_calc_known():
    r=calculate(Decimal("100"),"mangrove",1)  # 100*6*44/12=2200 gross, *0.9=1980
    assert r["gross_tco2e"]==2200.0 and r["result_tco2e"]==1980.0
def test_calc_invalid():
    with pytest.raises(ValueError): calculate(Decimal("0"),"mangrove",1)
def test_auth_and_project_flow():
    assert c.get("/api/v1/health").status_code==200
    assert c.get("/api/v1/projects").status_code==401
    tok=reg("dev1@test.local"); h={"Authorization":f"Bearer {tok}"}
    assert c.get("/api/v1/auth/me",headers=h).json()["email"]=="dev1@test.local"
    p=c.post("/api/v1/projects",headers=h,json={"name":"P1","ecosystem":"mangrove","area_ha":10}); assert p.status_code==201, p.text; pid=p.json()["id"]
    assert c.post(f"/api/v1/projects/{pid}/transition?new_status=approved",headers=h).status_code==400  # invalid transition
    assert c.post(f"/api/v1/projects/{pid}/transition?new_status=submitted",headers=h).status_code==200
    calc=c.post(f"/api/v1/projects/{pid}/calculations",headers=h,json={}); assert calc.status_code==201 and calc.json()["result_tco2e"]>0
    # issuance must fail: not approved
    iss=c.post("/api/v1/credits/issue",headers=h,json={"calculation_id":calc.json()["id"],"quantity":1}); assert iss.status_code in (400,403)
    # cross-user: buyer cannot edit
    tok2=reg("buy1@test.local","buyer"); h2={"Authorization":f"Bearer {tok2}"}
    assert c.put(f"/api/v1/projects/{pid}",headers=h2,json={"name":"x","ecosystem":"mangrove","area_ha":1}).status_code==403
    d=c.get("/api/v1/dashboard",headers=h); assert d.status_code==200 and d.json()["total_projects"]>=1
