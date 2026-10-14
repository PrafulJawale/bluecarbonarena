import sys; sys.path.insert(0,'.')
from app.db import SessionLocal,Base,engine
from app.models import *
from app.security import hash_pw
from app.calc import calculate
from decimal import Decimal
Base.metadata.create_all(bind=engine)
db=SessionLocal()
def user(email,name,role):
    u=db.query(User).filter_by(email=email).first()
    if not u: u=User(email=email,full_name=name,hashed_password=hash_pw("DemoPass123!"),role=role); db.add(u); db.commit(); db.refresh(u)
    return u
admin=user("admin@bluecarbonarena.local","Demo Admin","admin"); ver=user("verifier@bluecarbonarena.local","Demo Verifier","verifier"); dev=user("developer@bluecarbonarena.local","Demo Developer","developer"); res=user("researcher@bluecarbonarena.local","Demo Researcher","researcher"); buyer=user("buyer@bluecarbonarena.local","Demo Buyer","buyer"); comm=user("community@bluecarbonarena.local","Demo Community","community")
def proj(name,eco,area,status,lat,lon):
    p=db.query(Project).filter_by(name=name).first()
    if not p:
        p=Project(name=name,description="Clearly labelled demonstration project (fictional data).",owner_id=dev.id,country="India",region="Maharashtra coast",ecosystem=eco,area_ha=area,status=status,latitude=lat,longitude=lon,boundary={"type":"Polygon","coordinates":[[[lon-0.02,lat-0.02],[lon+0.02,lat-0.02],[lon+0.02,lat+0.02],[lon-0.02,lat+0.02],[lon-0.02,lat-0.02]]]})
        db.add(p); db.commit(); db.refresh(p)
    return p
p1=proj("Demo Sundari Mangrove Restoration","mangrove",120,"approved",19.05,72.85); p2=proj("Demo Seagrass Meadow Recovery","seagrass",80,"under_review",18.95,72.75); p3=proj("Demo Tidal Marsh Pilot","tidal_marsh",45,"draft",19.15,72.95); p4=proj("Demo Rejected Creek Site","mangrove",30,"rejected",19.0,72.8)
for p,t in [(p1,"Baseline site survey"),(p2,"Field photo transect")]:
    if not db.query(Evidence).filter_by(project_id=p.id,title=t).first(): db.add(Evidence(project_id=p.id,submitted_by=res.id,title=t,category="site_survey",description="Demo evidence metadata only - not proof of sequestration.",status="pending"))
db.commit()
# calc + issuance + listing for approved p1 idempotently
if not db.query(CalculationRun).filter_by(project_id=p1.id).first():
    r=calculate(Decimal("120"),"mangrove",5); run=CalculationRun(project_id=p1.id,created_by=dev.id,methodology_version="BCA-ILLUSTRATIVE v1.0",inputs={"area_ha":120,"ecosystem":"mangrove","years":5},result_tco2e=r["result_tco2e"],gross_tco2e=r["gross_tco2e"],steps=r["steps"],warnings=r["warnings"]); db.add(run); db.commit(); db.refresh(run)
    b=CreditBatch(serial="BCA-DEMO-SEED-001",project_id=p1.id,calculation_id=run.id,quantity=1000,available=1000,issued_by=ver.id); db.add(b); db.commit(); db.refresh(b)
    db.add(Listing(batch_id=b.id,seller_id=dev.id,title="Demo Mangrove Credits (Simulated)",price_usd=Decimal("12.50"),quantity=1000,available=1000)); db.commit()
print("Seed complete (idempotent)")
