
from fastapi import FastAPI,Depends,HTTPException,UploadFile,File,Form,Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional
import hashlib,os,uuid,pathlib
from decimal import Decimal
from .db import Base,engine,get_db,SessionLocal
from .models import *
from .security import hash_pw,verify_pw,create_token,get_current_user,require
from .config import settings
from .calc import calculate

app=FastAPI(title="BLUECARBON ARENA API",version="1.0.0")
app.add_middleware(CORSMiddleware,allow_origins=[o.strip() for o in settings.cors_origins.split(",")],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
Base.metadata.create_all(bind=engine)  # dev convenience; Alembic migration provided for production

def audit(db,actor,action,rt,rid,meta=None):
    db.add(AuditLog(actor_id=actor.id if actor else None,action=action,resource_type=rt,resource_id=str(rid) if rid else None,meta=meta or {}))
def pub_user(u): return {"id":u.id,"email":u.email,"full_name":u.full_name,"role":u.role,"is_active":u.is_active}
def pub_project(p): return {"id":p.id,"name":p.name,"description":p.description,"owner_id":p.owner_id,"country":p.country,"region":p.region,"ecosystem":p.ecosystem,"area_ha":float(p.area_ha),"status":p.status,"start_date":p.start_date,"reporting_years":p.reporting_years,"methodology":p.methodology,"latitude":float(p.latitude) if p.latitude is not None else None,"longitude":float(p.longitude) if p.longitude is not None else None,"boundary":p.boundary,"created_at":p.created_at.isoformat() if p.created_at else None}
def can_view(u,p): return u.role in ("admin","verifier") or p.owner_id==u.id or u.role in ("researcher","community","buyer")
def can_edit(u,p): return u.role=="admin" or p.owner_id==u.id

class AuthIn(BaseModel): email:str; password:str; full_name:str=""; role:str="community"
class ProjectIn(BaseModel): name:str; description:str=""; country:str="India"; region:str=""; ecosystem:str; area_ha:float; start_date:str="2024-01-01"; reporting_years:int=5; methodology:str="BCA-ILLUSTRATIVE v1.0"; latitude:Optional[float]=None; longitude:Optional[float]=None; boundary:Optional[dict]=None
class DecisionIn(BaseModel): decision:str; reason:str; checklist:Optional[dict]=None
class CalcIn(BaseModel): uncertainty:float=0.10; baseline_tco2e:float=0
class ListingIn(BaseModel): batch_id:int; title:str; price_usd:float; quantity:float
class OrderIn(BaseModel): quantity:float; idempotency_key:Optional[str]=None
class IssueIn(BaseModel): calculation_id:int; quantity:float

@app.get("/api/v1/health")
def health(): return {"status":"ok","service":"BLUECARBON ARENA","demo_mode":settings.demo_mode}
@app.post("/api/v1/auth/register")
def register(data:AuthIn,db:Session=Depends(get_db)):
    if data.role not in ("developer","researcher","buyer","community"): raise HTTPException(400,"Self-registration role not allowed")
    if db.query(User).filter_by(email=data.email).first(): raise HTTPException(409,"Email already registered")
    if len(data.password)<8: raise HTTPException(400,"Password must be at least 8 characters")
    u=User(email=data.email,full_name=data.full_name or data.email.split("@")[0],hashed_password=hash_pw(data.password),role=data.role); db.add(u); db.commit(); db.refresh(u)
    return {"access_token":create_token(u),"user":pub_user(u)}
@app.post("/api/v1/auth/login")
def login(data:AuthIn,db:Session=Depends(get_db)):
    u=db.query(User).filter_by(email=data.email).first()
    if not u or not verify_pw(data.password,u.hashed_password): raise HTTPException(401,"Invalid email or password")
    return {"access_token":create_token(u),"user":pub_user(u)}
@app.get("/api/v1/auth/me")
def me(u:User=Depends(get_current_user)): return pub_user(u)
@app.post("/api/v1/auth/logout")
def logout(u:User=Depends(get_current_user)): return {"detail":"Logged out. Discard token client-side; token expires per configured lifetime."}

@app.get("/api/v1/users")
def users(db:Session=Depends(get_db),u:User=Depends(require("admin"))): return [pub_user(x) for x in db.query(User).all()]
@app.patch("/api/v1/users/{uid}/role")
def set_role(uid:int,role:str=Query(...),db:Session=Depends(get_db),u:User=Depends(require("admin"))):
    if role not in ("admin","verifier","developer","researcher","buyer","community"): raise HTTPException(400,"bad role")
    t=db.get(User,uid)
    if not t: raise HTTPException(404,"user not found")
    t.role=role; audit(db,u,"user.role_change","user",uid,{"role":role}); db.commit(); return pub_user(t)

@app.get("/api/v1/projects")
def list_projects(db:Session=Depends(get_db),u:User=Depends(get_current_user),status:Optional[str]=None,ecosystem:Optional[str]=None,skip:int=0,limit:int=100):
    q=db.query(Project)
    if u.role=="developer": q=q.filter((Project.owner_id==u.id)|(Project.status.in_(["approved","submitted","under_review"])))
    if status: q=q.filter_by(status=status)
    if ecosystem: q=q.filter_by(ecosystem=ecosystem)
    return [pub_project(p) for p in q.offset(skip).limit(min(limit,200)).all()]
@app.post("/api/v1/projects",status_code=201)
def create_project(data:ProjectIn,db:Session=Depends(get_db),u:User=Depends(require("developer","admin"))):
    if data.area_ha<=0: raise HTTPException(400,"area must be positive")
    if data.ecosystem not in ("mangrove","tidal_marsh","seagrass"): raise HTTPException(400,"invalid ecosystem")
    p=Project(**data.model_dump(),owner_id=u.id); db.add(p); db.commit(); db.refresh(p); audit(db,u,"project.create","project",p.id); db.commit(); return pub_project(p)
@app.get("/api/v1/projects/{pid}")
def get_project(pid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if not can_view(u,p): raise HTTPException(403,"Forbidden")
    d=pub_project(p); d["evidence_count"]=db.query(Evidence).filter_by(project_id=pid).count(); d["calculation_count"]=db.query(CalculationRun).filter_by(project_id=pid).count(); return d
TRANSITIONS={"draft":["submitted"],"submitted":["under_review"],"under_review":["approved","rejected"],"rejected":["submitted"],"approved":[]}
@app.post("/api/v1/projects/{pid}/transition")
def transition(pid:int,new_status:str=Query(...),db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if new_status not in TRANSITIONS.get(p.status,[]): raise HTTPException(400,f"Invalid transition {p.status} -> {new_status}")
    if new_status in ("submitted",) and not can_edit(u,p): raise HTTPException(403,"Only owner can submit")
    if new_status in ("approved","rejected","under_review") and u.role not in ("verifier","admin"): raise HTTPException(403,"Only verifier/admin")
    p.status=new_status; audit(db,u,"project.transition","project",pid,{"to":new_status}); db.commit(); return pub_project(p)
@app.put("/api/v1/projects/{pid}")
def update_project(pid:int,data:ProjectIn,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if not can_edit(u,p): raise HTTPException(403,"Forbidden")
    if p.status=="approved": raise HTTPException(400,"Approved projects cannot be edited without new review cycle")
    for k,v in data.model_dump().items(): setattr(p,k,v)
    audit(db,u,"project.update","project",pid); db.commit(); return pub_project(p)
@app.delete("/api/v1/projects/{pid}")
def delete_project(pid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if not can_edit(u,p): raise HTTPException(403,"Forbidden")
    db.delete(p); audit(db,u,"project.delete","project",pid); db.commit(); return {"detail":"deleted"}

@app.post("/api/v1/projects/{pid}/evidence",status_code=201)
async def add_evidence(pid:int,title:str=Form(...),category:str=Form(...),description:str=Form(""),file:UploadFile|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if u.role not in ("admin","developer","researcher","community","verifier"): raise HTTPException(403,"Forbidden")
    stored=None; sha=None; size=None; ctype=None
    if file and file.filename:
        content=await file.read()
        if len(content)>10*1024*1024: raise HTTPException(400,"File exceeds 10MB")
        if file.content_type not in ("image/jpeg","image/png","application/pdf","text/plain","text/csv"): raise HTTPException(400,"File type not allowed")
        stored=f"{uuid.uuid4().hex}{pathlib.Path(file.filename).suffix[:10]}"; os.makedirs(settings.upload_dir,exist_ok=True)
        pathlib.Path(settings.upload_dir,stored).write_bytes(content); sha=hashlib.sha256(content).hexdigest(); size=len(content); ctype=file.content_type
    e=Evidence(project_id=pid,submitted_by=u.id,title=title,category=category,description=description,filename=file.filename if file else None,stored_name=stored,content_type=ctype,size_bytes=size,sha256=sha)
    db.add(e); db.commit(); db.refresh(e); audit(db,u,"evidence.submit","evidence",e.id,{"project_id":pid}); db.commit()
    return {"id":e.id,"project_id":e.project_id,"title":e.title,"category":e.category,"status":e.status,"sha256":e.sha256,"filename":e.filename,"created_at":e.created_at.isoformat()}
@app.get("/api/v1/projects/{pid}/evidence")
def list_evidence(pid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p or not can_view(u,p): raise HTTPException(403,"Forbidden")
    return [{"id":e.id,"project_id":e.project_id,"title":e.title,"category":e.category,"description":e.description,"status":e.status,"filename":e.filename,"sha256":e.sha256,"reviewer_notes":e.reviewer_notes,"submitted_by":e.submitted_by,"created_at":e.created_at.isoformat()} for e in db.query(Evidence).filter_by(project_id=pid).all()]
@app.patch("/api/v1/evidence/{eid}/review")
def review_evidence(eid:int,status:str=Query(...),notes:str=Query(""),db:Session=Depends(get_db),u:User=Depends(require("verifier","admin"))):
    e=db.get(Evidence,eid)
    if not e: raise HTTPException(404,"not found")
    if status not in ("accepted","rejected","pending"): raise HTTPException(400,"bad status")
    e.status=status; e.reviewer_notes=notes; audit(db,u,"evidence.review","evidence",eid,{"status":status}); db.commit(); return {"id":e.id,"status":e.status}
@app.get("/api/v1/evidence/{eid}/download")
def download(eid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    e=db.get(Evidence,eid)
    if not e or not e.stored_name: raise HTTPException(404,"No file")
    p=db.get(Project,e.project_id)
    if not can_view(u,p) and e.submitted_by!=u.id: raise HTTPException(403,"Forbidden")
    path=pathlib.Path(settings.upload_dir,e.stored_name)
    if not path.exists(): raise HTTPException(404,"File missing")
    return FileResponse(path,filename=e.filename or "evidence")

@app.post("/api/v1/projects/{pid}/decisions")
def decide(pid:int,data:DecisionIn,db:Session=Depends(get_db),u:User=Depends(require("verifier","admin"))):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if data.decision not in ("approved","rejected"): raise HTTPException(400,"decision must be approved/rejected")
    if not data.reason.strip(): raise HTTPException(400,"Reason required")
    if p.status not in ("under_review","submitted"): raise HTTPException(400,"Project is not under review")
    d=VerificationDecision(project_id=pid,reviewer_id=u.id,decision=data.decision,reason=data.reason,checklist=data.checklist); p.status=data.decision; db.add(d); audit(db,u,"verification.decision","project",pid,{"decision":data.decision}); db.commit(); return {"id":d.id,"decision":d.decision,"project_status":p.status}
@app.get("/api/v1/projects/{pid}/decisions")
def decisions(pid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    return [{"id":d.id,"decision":d.decision,"reason":d.reason,"reviewer_id":d.reviewer_id,"created_at":d.created_at.isoformat()} for d in db.query(VerificationDecision).filter_by(project_id=pid).all()]

@app.post("/api/v1/projects/{pid}/calculations",status_code=201)
def run_calc(pid:int,data:CalcIn,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    try: r=calculate(Decimal(str(p.area_ha)),p.ecosystem,p.reporting_years,Decimal(str(data.uncertainty)),Decimal(str(data.baseline_tco2e)))
    except ValueError as e: raise HTTPException(400,str(e))
    inputs={"area_ha":float(p.area_ha),"ecosystem":p.ecosystem,"years":p.reporting_years,"uncertainty":data.uncertainty,"baseline_tco2e":data.baseline_tco2e}
    run=CalculationRun(project_id=pid,created_by=u.id,methodology_version="BCA-ILLUSTRATIVE v1.0",inputs=inputs,result_tco2e=r["result_tco2e"],gross_tco2e=r["gross_tco2e"],steps=r["steps"],warnings=r["warnings"]); db.add(run); db.commit(); db.refresh(run); audit(db,u,"calculation.run","calculation",run.id,{"project_id":pid}); db.commit()
    return {"id":run.id,"project_id":pid,"result_tco2e":float(run.result_tco2e),"gross_tco2e":float(run.gross_tco2e),"inputs":inputs,"steps":r["steps"],"warnings":r["warnings"],"methodology_version":run.methodology_version,"created_at":run.created_at.isoformat()}
@app.get("/api/v1/projects/{pid}/calculations")
def list_calc(pid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    return [{"id":r.id,"result_tco2e":float(r.result_tco2e),"gross_tco2e":float(r.gross_tco2e),"inputs":r.inputs,"steps":r.steps,"warnings":r.warnings,"methodology_version":r.methodology_version,"created_at":r.created_at.isoformat()} for r in db.query(CalculationRun).filter_by(project_id=pid).order_by(CalculationRun.id.desc()).all()]

@app.post("/api/v1/credits/issue",status_code=201)
def issue(data:IssueIn,db:Session=Depends(get_db),u:User=Depends(require("verifier","admin"))):
    calc=db.get(CalculationRun,data.calculation_id)
    if not calc: raise HTTPException(404,"calculation not found")
    p=db.get(Project,calc.project_id)
    if p.status!="approved": raise HTTPException(400,"Issuance requires an approved project")
    if data.quantity<=0 or Decimal(str(data.quantity))>Decimal(str(calc.result_tco2e)): raise HTTPException(400,"Quantity exceeds eligible calculated quantity")
    if db.query(CreditBatch).filter_by(calculation_id=calc.id).first(): raise HTTPException(409,"Credits already issued for this calculation (duplicate prevented)")
    b=CreditBatch(serial=f"BCA-DEMO-{calc.project_id}-{calc.id}-{uuid.uuid4().hex[:6].upper()}",project_id=p.id,calculation_id=calc.id,quantity=data.quantity,available=data.quantity,issued_by=u.id); db.add(b)
    try: db.commit()
    except Exception: db.rollback(); raise HTTPException(409,"Duplicate issuance prevented")
    db.refresh(b); audit(db,u,"credit.issue","credit_batch",b.id,{"quantity":data.quantity}); db.commit()
    return {"id":b.id,"serial":b.serial,"quantity":float(b.quantity),"available":float(b.available),"calculation_id":b.calculation_id,"project_id":b.project_id,"label":"Simulated demonstration credits - not externally verified or tradable"}
@app.get("/api/v1/credits")
def credits(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    return [{"id":b.id,"serial":b.serial,"project_id":b.project_id,"calculation_id":b.calculation_id,"quantity":float(b.quantity),"available":float(b.available),"sold":float(b.sold),"retired":float(b.retired),"status":b.status} for b in db.query(CreditBatch).all()]

@app.get("/api/v1/listings")
def listings(db:Session=Depends(get_db),q:str="",skip:int=0,limit:int=50):
    rows=db.query(Listing).filter_by(status="active").all()
    out=[]
    for l in rows:
        b=db.get(CreditBatch,l.batch_id); p=db.get(Project,b.project_id) if b else None
        if q and q.lower() not in (l.title+" "+(p.name if p else "")).lower(): continue
        out.append({"id":l.id,"title":l.title,"price_usd":float(l.price_usd),"quantity":float(l.quantity),"available":float(l.available),"batch_id":l.batch_id,"project_name":p.name if p else "","ecosystem":p.ecosystem if p else "","project_id":p.id if p else None,"status":l.status})
    return out[skip:skip+limit]
@app.post("/api/v1/listings",status_code=201)
def create_listing(data:ListingIn,db:Session=Depends(get_db),u:User=Depends(require("developer","admin"))):
    b=db.get(CreditBatch,data.batch_id)
    if not b: raise HTTPException(404,"batch not found")
    p=db.get(Project,b.project_id)
    if u.role!="admin" and p.owner_id!=u.id: raise HTTPException(403,"Only project owner can list its credits")
    if data.quantity<=0 or Decimal(str(data.quantity))>Decimal(str(b.available)): raise HTTPException(400,"Quantity exceeds available credits")
    l=Listing(batch_id=b.id,seller_id=u.id,title=data.title,price_usd=data.price_usd,quantity=data.quantity,available=data.quantity); db.add(l); db.commit(); db.refresh(l); audit(db,u,"listing.create","listing",l.id); db.commit(); return {"id":l.id,"available":float(l.available)}
@app.post("/api/v1/listings/{lid}/purchase",status_code=201)
def purchase(lid:int,data:OrderIn,db:Session=Depends(get_db),u:User=Depends(require("buyer","admin"))):
    if data.idempotency_key and db.query(Order).filter_by(idempotency_key=data.idempotency_key).first(): raise HTTPException(409,"Duplicate purchase submission prevented")
    l=db.query(Listing).filter_by(id=lid).with_for_update().first()
    if not l or l.status!="active": raise HTTPException(400,"Listing not active")
    if data.quantity<=0 or Decimal(str(data.quantity))>Decimal(str(l.available)): raise HTTPException(400,"Insufficient available quantity")
    total=(Decimal(str(data.quantity))*Decimal(str(l.price_usd))).quantize(Decimal("0.01"))
    l.available=Decimal(str(l.available))-Decimal(str(data.quantity)); b=db.get(CreditBatch,l.batch_id); b.available=Decimal(str(b.available))-Decimal(str(data.quantity)); b.sold=Decimal(str(b.sold))+Decimal(str(data.quantity))
    o=Order(listing_id=lid,buyer_id=u.id,quantity=data.quantity,unit_price=l.price_usd,total_usd=total,idempotency_key=data.idempotency_key); db.add(o); db.commit(); db.refresh(o); audit(db,u,"order.purchase","order",o.id,{"listing_id":lid,"note":"simulated, no real payment"}); db.commit()
    return {"id":o.id,"total_usd":float(o.total_usd),"quantity":float(o.quantity),"status":o.status,"note":"Simulated demo purchase - no real payment processed"}
@app.get("/api/v1/orders")
def orders(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    q=db.query(Order)
    if u.role not in ("admin",): q=q.filter_by(buyer_id=u.id)
    return [{"id":o.id,"listing_id":o.listing_id,"quantity":float(o.quantity),"total_usd":float(o.total_usd),"status":o.status,"created_at":o.created_at.isoformat()} for o in q.all()]

@app.get("/api/v1/dashboard")
def dashboard(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    q=db.query(Project)
    if u.role=="developer": q=q.filter_by(owner_id=u.id)
    projects=q.all()
    def c(s): return sum(1 for p in projects if p.status==s)
    eco={}
    for p in projects: eco[p.ecosystem]=eco.get(p.ecosystem,0)+1
    batches=db.query(CreditBatch).all(); listings=db.query(Listing).filter_by(status="active").all()
    return {"total_projects":len(projects),"draft":c("draft"),"submitted":c("submitted"),"under_review":c("under_review"),"approved":c("approved"),"rejected":c("rejected"),"evidence_pending":db.query(Evidence).filter_by(status="pending").count(),"calculations":db.query(CalculationRun).count(),"potential_tco2e":float(sum(Decimal(str(r.result_tco2e)) for r in db.query(CalculationRun).all())),"issued_credits":float(sum(Decimal(str(b.quantity)) for b in batches)),"available_credits":float(sum(Decimal(str(b.available)) for b in batches)),"active_listings":len(listings),"ecosystem_distribution":eco,"recent_projects":[pub_project(p) for p in projects[-5:]]}
@app.get("/api/v1/audit")
def audit_list(db:Session=Depends(get_db),u:User=Depends(require("admin","verifier"))):
    return [{"id":a.id,"actor_id":a.actor_id,"action":a.action,"resource_type":a.resource_type,"resource_id":a.resource_id,"meta":a.meta,"created_at":a.created_at.isoformat()} for a in db.query(AuditLog).order_by(AuditLog.id.desc()).limit(200).all()]
