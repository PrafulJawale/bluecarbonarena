from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, field_validator
from typing import Optional
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
import hashlib, os, uuid, pathlib, json, re
from decimal import Decimal
from datetime import datetime, timezone
from .db import Base, engine, get_db, SessionLocal
from .models import *
from .security import hash_pw, verify_pw, create_token, get_current_user, require
from .config import settings
from .calc import calculate, METHOD_VERSION, RATES

def _limiter_key(request: Request) -> str:
    return get_remote_address(request)


# Tests/CI can disable rate limiting with RATE_LIMIT_ENABLED=false (never in production).
limiter = Limiter(key_func=_limiter_key, enabled=settings.rate_limit_enabled)


def _safe_geom(b):
    """Validate GeoJSON Polygon geometry (lon/lat ordering, closed ring)."""
    if b is None:
        return None
    try:
        if b.get("type") != "Polygon":
            raise ValueError("only Polygon supported")
        rings = b.get("coordinates")
        if not isinstance(rings, list) or not rings:
            raise ValueError("missing coordinates")
        for ring in rings:
            if len(ring) < 4:
                raise ValueError("ring needs >=4 positions")
            if ring[0] != ring[-1]:
                raise ValueError("ring must be closed")
            for pos in ring:
                lon, lat = pos[0], pos[1]
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    raise ValueError("position out of WGS84 bounds")
        return b
    except Exception as e:
        raise HTTPException(422, f"Invalid boundary geometry: {e}")


app = FastAPI(title="BLUECARBON ARENA API", version="1.0.0",
              description="Project management & illustrative blue-carbon accounting platform. "
                          "Not an accredited registry; demo credits are simulated.")
app.state.limiter = limiter
if settings.rate_limit_enabled:
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware,
                   allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
# Dev convenience; Alembic migrations are the source of truth for production.
Base.metadata.create_all(bind=engine)


@app.exception_handler(Exception)
async def unhandled_exc(request: Request, exc: Exception):
    # Never leak stack traces / internals to clients. Server logs keep the detail.
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def audit(db, actor, action, rt, rid, meta=None):
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action,
                    resource_type=rt, resource_id=str(rid) if rid else None, meta=meta or {}))


def pub_user(u): return {"id": u.id, "email": u.email, "full_name": u.full_name,
                        "role": u.role, "is_active": u.is_active}


def pub_project(p): return {"id": p.id, "name": p.name, "description": p.description,
                            "owner_id": p.owner_id, "country": p.country, "region": p.region,
                            "ecosystem": p.ecosystem, "area_ha": float(p.area_ha), "status": p.status,
                            "start_date": p.start_date, "reporting_years": p.reporting_years,
                            "methodology": p.methodology,
                            "latitude": float(p.latitude) if p.latitude is not None else None,
                            "longitude": float(p.longitude) if p.longitude is not None else None,
                            "boundary": p.boundary,
                            "data_quality": p.data_quality,
                            "created_at": p.created_at.isoformat() if p.created_at else None,
                            "updated_at": p.updated_at.isoformat() if p.updated_at else None}


def can_view(u, p): return u.role in ("admin", "verifier") or p.owner_id == u.id or u.role in ("researcher", "community", "buyer")
def can_edit(u, p): return u.role == "admin" or p.owner_id == u.id


class AuthIn(BaseModel): email: str; password: str; full_name: str = ""; role: str = "community"
class ProjectIn(BaseModel):
    name: str; description: str = ""; country: str = "India"; region: str = ""
    ecosystem: str; area_ha: float; start_date: str = "2024-01-01"; reporting_years: int = 5
    methodology: str = METHOD_VERSION
    latitude: Optional[float] = None; longitude: Optional[float] = None
    boundary: Optional[dict] = None

    @field_validator("start_date")
    @classmethod
    def _date_ok(cls, v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("start_date must be YYYY-MM-DD")
        return v

    @field_validator("latitude", "longitude")
    @classmethod
    def _coord_range(cls, v, info):
        if v is None:
            return v
        lim = 90 if info.field_name == "latitude" else 180
        if not -lim <= v <= lim:
            raise ValueError(f"{info.field_name} out of range")
        return v


class DecisionIn(BaseModel): decision: str; reason: str; checklist: Optional[dict] = None
class CalcIn(BaseModel): uncertainty: float = 0.10; baseline_tco2e: float = 0
class ListingIn(BaseModel): batch_id: int; title: str; price_usd: float; quantity: float
class OrderIn(BaseModel): quantity: float; idempotency_key: Optional[str] = None
class IssueIn(BaseModel): calculation_id: int; quantity: float


@app.get("/api/v1/health")
def health(): return {"status": "ok", "service": "BLUECARBON ARENA", "demo_mode": settings.demo_mode}


@app.get("/api/v1/health/ready")
def health_ready(db: Session = Depends(get_db)):
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ok", "database": "reachable"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "unreachable"})


@app.post("/api/v1/auth/register")
@limiter.limit(settings.rate_limit_register)
def register(request: Request, data: AuthIn, db: Session = Depends(get_db)):
    if not settings.allow_registration:
        raise HTTPException(403, "Registration is disabled on this deployment")
    if data.role not in ("developer", "researcher", "buyer", "community"):
        raise HTTPException(400, "Self-registration role not allowed")
    if len(data.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if db.query(User).filter_by(email=data.email).first():
        raise HTTPException(409, "Email already registered")
    u = User(email=data.email, full_name=data.full_name or data.email.split("@")[0],
             hashed_password=hash_pw(data.password), role=data.role)
    db.add(u); db.commit(); db.refresh(u)
    audit(db, u, "auth.register", "user", u.id, {"role": data.role}); db.commit()
    return {"access_token": create_token(u), "user": pub_user(u)}


@app.post("/api/v1/auth/login")
@limiter.limit(settings.rate_limit_login)
def login(request: Request, data: AuthIn, db: Session = Depends(get_db)):
    u = db.query(User).filter_by(email=data.email).first()
    # Same generic error regardless of which factor failed — no user enumeration.
    if not u or not u.is_active or not verify_pw(data.password, u.hashed_password):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": create_token(u), "user": pub_user(u)}


@app.get("/api/v1/auth/me")
def me(u: User = Depends(get_current_user)): return pub_user(u)


@app.post("/api/v1/auth/logout")
def logout(u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Server-side invalidation: bump token_version so all previously issued tokens fail auth.
    u.token_version = (u.token_version or 0) + 1
    audit(db, u, "auth.logout", "user", u.id); db.commit()
    return {"detail": "Logged out; all previous tokens for this account are now invalid."}

@app.get("/api/v1/users")
def users(db:Session=Depends(get_db),u:User=Depends(require("admin")),skip:int=0,limit:int=Query(100,le=500)):
    return {"items":[pub_user(x) for x in db.query(User).order_by(User.id).offset(skip).limit(limit).all()],"total":db.query(User).count()}
class RoleIn(BaseModel): role:str
class ActiveIn(BaseModel): is_active:bool
@app.patch("/api/v1/users/{uid}/role")
def set_role(uid:int,data:RoleIn,db:Session=Depends(get_db),u:User=Depends(require("admin"))):
    role=data.role
    if role not in ("admin","verifier","developer","researcher","buyer","community"): raise HTTPException(400,"bad role")
    t=db.get(User,uid)
    if not t: raise HTTPException(404,"user not found")
    t.role=role; t.token_version=(t.token_version or 0)+1  # revoke tokens so stale claims can't be reused
    audit(db,u,"user.role_change","user",uid,{"role":role}); db.commit(); return pub_user(t)
@app.patch("/api/v1/users/{uid}/active")
def set_active(uid:int,data:ActiveIn,db:Session=Depends(get_db),u:User=Depends(require("admin"))):
    t=db.get(User,uid)
    if not t: raise HTTPException(404,"user not found")
    if t.id==u.id: raise HTTPException(400,"You cannot deactivate your own account")
    t.is_active=data.is_active
    if not data.is_active: t.token_version=(t.token_version or 0)+1  # server-side session revocation
    audit(db,u,"user.active_change","user",uid,{"is_active":data.is_active}); db.commit(); return pub_user(t)

@app.get("/api/v1/projects")
def list_projects(db:Session=Depends(get_db),u:User=Depends(get_current_user),status:Optional[str]=None,ecosystem:Optional[str]=None,q:Optional[str]=None,skip:int=0,limit:int=Query(100,le=200)):
    from sqlalchemy import or_
    qy=db.query(Project)
    member_ids=[m.project_id for m in db.query(ProjectMember).filter_by(user_id=u.id).all()]
    if u.role=="developer":
        conds=[Project.owner_id==u.id]
        if member_ids: conds.append(Project.id.in_(member_ids))
        qy=qy.filter(or_(*conds))
    if status: qy=qy.filter_by(status=status)
    if ecosystem: qy=qy.filter_by(ecosystem=ecosystem)
    if q: qy=qy.filter(or_(Project.name.ilike(f"%{q}%"),Project.region.ilike(f"%{q}%"),Project.country.ilike(f"%{q}%")))
    total=qy.count()
    return {"items":[pub_project(p) for p in qy.order_by(Project.id.desc()).offset(skip).limit(min(limit,200)).all()],"total":total}

def _validate_project_fields(data:ProjectIn):
    if data.area_ha<=0: raise HTTPException(400,"area_ha must be positive (unit: hectares)")
    if data.ecosystem not in RATES: raise HTTPException(400,f"invalid ecosystem; allowed: {', '.join(sorted(RATES))}")
    if data.reporting_years<=0 or data.reporting_years>100: raise HTTPException(400,"reporting_years must be 1-100")
    _safe_geom(data.boundary)
    if (data.latitude is None)!=(data.longitude is None): raise HTTPException(422,"latitude and longitude must be provided together")

@app.post("/api/v1/projects",status_code=201)
def create_project(data:ProjectIn,db:Session=Depends(get_db),u:User=Depends(require("developer","admin"))):
    _validate_project_fields(data)
    p=Project(**data.model_dump(),owner_id=u.id); db.add(p); db.flush()
    audit(db,u,"project.create","project",p.id); db.commit(); db.refresh(p); return pub_project(p)

@app.get("/api/v1/projects/{pid}")
def get_project(pid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if not can_view(u,p): raise HTTPException(403,"Forbidden")
    d=pub_project(p); d["evidence_count"]=db.query(Evidence).filter_by(project_id=pid).count()
    d["calculation_count"]=db.query(CalculationRun).filter_by(project_id=pid).count()
    d["members"]=[{"user_id":m.user_id,"role":m.role} for m in db.query(ProjectMember).filter_by(project_id=pid).all()]
    last=db.query(CalculationRun).filter_by(project_id=pid).order_by(CalculationRun.id.desc()).first()
    d["last_calculation_id"]=last.id if last else None
    return d

# Documented state machine. Decisions (approve/reject) go through the verification endpoint,
# NOT this generic transition endpoint — a project can never become approved by clicking a button here.
TRANSITIONS={"draft":["submitted"],"submitted":["under_review","draft"],"under_review":[],"rejected":["submitted"],"approved":[]}
TRANSITION_ROLES={"submitted":("owner",),"under_review":("verifier","admin"),"draft":("owner",)}
@app.post("/api/v1/projects/{pid}/transition")
def transition(pid:int,new_status:str=Query(...),db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if new_status not in TRANSITIONS.get(p.status,[]): raise HTTPException(400,f"Invalid transition {p.status} -> {new_status}")
    allowed=TRANSITION_ROLES.get(new_status,())
    if allowed==("owner",):
        if not can_edit(u,p): raise HTTPException(403,"Only owner/admin can perform this transition")
    elif u.role not in allowed: raise HTTPException(403,f"Only {', '.join(allowed)} may perform this transition")
    p.status=new_status; audit(db,u,"project.transition","project",pid,{"to":new_status}); db.commit(); return pub_project(p)

MATERIAL_FIELDS=("area_ha","ecosystem","reporting_years","start_date","methodology","boundary","latitude","longitude")
@app.put("/api/v1/projects/{pid}")
def update_project(pid:int,data:ProjectIn,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if not can_edit(u,p): raise HTTPException(403,"Forbidden")
    if p.status in ("submitted","under_review"): raise HTTPException(400,"Cannot edit a project while it is in review; ask the reviewer to return it to draft first")
    dump=data.model_dump()
    material=any((getattr(p,k) if k not in ("boundary",) else json.dumps(getattr(p,k),sort_keys=True))!=dump[k] for k in MATERIAL_FIELDS)
    _validate_project_fields(data)
    if p.status=="approved" and material:
        p.status="draft"; p.data_quality="stale"  # material edits force a new review + recalculation cycle
    elif material:
        p.data_quality="stale"
    for k,v in dump.items(): setattr(p,k,v)
    audit(db,u,"project.update","project",pid,{"material":material,"reopened":p.status=="draft" and material}); db.commit(); return pub_project(p)

@app.delete("/api/v1/projects/{pid}")
def delete_project(pid:int,db:Session=Depends(get_db),u:User=Depends(require("admin"))):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    # Soft-delete preserves traceability of evidence/calculations/credits history.
    p.status="archived"; p.data_quality="stale"
    audit(db,u,"project.archive","project",pid); db.commit()
    return {"detail":"Project archived (soft delete). Records preserved for traceability."}

class MemberIn(BaseModel): user_id:int; role:str="collaborator"
@app.get("/api/v1/projects/{pid}/members")
def get_members(pid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p or not can_view(u,p): raise HTTPException(403,"Forbidden")
    return [{"user_id":m.user_id,"role":m.role} for m in db.query(ProjectMember).filter_by(project_id=pid).all()]
@app.post("/api/v1/projects/{pid}/members",status_code=201)
def add_member(pid:int,data:MemberIn,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if not can_edit(u,p): raise HTTPException(403,"Only owner/admin manage members")
    if not db.get(User,data.user_id): raise HTTPException(404,"user not found")
    if db.query(ProjectMember).filter_by(project_id=pid,user_id=data.user_id).first(): raise HTTPException(409,"already a member")
    db.add(ProjectMember(project_id=pid,user_id=data.user_id,role=data.role))
    audit(db,u,"project.member_add","project",pid,{"user_id":data.user_id}); db.commit(); return {"detail":"added"}
@app.delete("/api/v1/projects/{pid}/members/{uid}")
def del_member(pid:int,uid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if not can_edit(u,p): raise HTTPException(403,"Only owner/admin manage members")
    m=db.query(ProjectMember).filter_by(project_id=pid,user_id=uid).first()
    if not m: raise HTTPException(404,"member not found")
    db.delete(m); audit(db,u,"project.member_remove","project",pid,{"user_id":uid}); db.commit(); return {"detail":"removed"}

EVIDENCE_CATEGORIES=("field_photo","site_survey","project_documentation","monitoring_report","satellite_derived","ecological_measurement","administrative")
MIME_MAGIC={b"\xff\xd8\xff":"image/jpeg",b"\x89PNG":"image/png",b"%PDF":"application/pdf"}
ALLOWED_MIMES=set(MIME_MAGIC.values())|{"text/plain","text/csv"}

@app.post("/api/v1/projects/{pid}/evidence",status_code=201)
async def add_evidence(pid:int,title:str=Form(...),category:str=Form(...),description:str=Form(""),file:UploadFile|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if u.role=="buyer": raise HTTPException(403,"Buyers may not submit evidence")
    member = can_edit(u,p) or db.query(ProjectMember).filter_by(project_id=pid,user_id=u.id).first()
    if u.role in ("developer","researcher") and not member:
        raise HTTPException(403,"Only project members may submit evidence for this project")
    if u.role=="community" and not member:
        # Community participants may contribute feedback-style evidence only on projects they belong to.
        raise HTTPException(403,"Community participants must be project members to submit evidence")
    if category not in EVIDENCE_CATEGORIES: raise HTTPException(400,f"invalid category; allowed: {', '.join(EVIDENCE_CATEGORIES)}")
    stored=None; sha=None; size=None; ctype=None
    if file and file.filename:
        content=await file.read()
        if len(content)>10*1024*1024: raise HTTPException(413,"File exceeds 10MB limit")
        if len(content)==0: raise HTTPException(400,"Empty file")
        # Validate actual content via magic bytes when identifiable; otherwise trust declared type only for text types.
        detected=None
        for magic,mime in MIME_MAGIC.items():
            if content.startswith(magic): detected=mime; break
        declared=file.content_type or ""
        if detected and detected!=declared: raise HTTPException(400,"File content does not match declared type")
        if (detected or declared) not in ALLOWED_MIMES: raise HTTPException(400,"File type not allowed (jpeg/png/pdf/txt/csv)")
        suffix=pathlib.Path(file.filename).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,9}",suffix): suffix=""  # safe server-side filename, no traversal/executable extensions
        stored=f"{uuid.uuid4().hex}{suffix}"
        os.makedirs(settings.upload_dir,exist_ok=True)
        pathlib.Path(settings.upload_dir,stored).write_bytes(content)
        sha=hashlib.sha256(content).hexdigest(); size=len(content); ctype=detected or declared
    e=Evidence(project_id=pid,submitted_by=u.id,title=title,category=category,description=description,filename=file.filename if file else None,stored_name=stored,content_type=ctype,size_bytes=size,sha256=sha)
    db.add(e); db.flush(); audit(db,u,"evidence.submit","evidence",e.id,{"project_id":pid}); db.commit(); db.refresh(e)
    return {"id":e.id,"project_id":e.project_id,"title":e.title,"category":e.category,"status":e.status,"sha256":e.sha256,"filename":e.filename,"created_at":e.created_at.isoformat()}

@app.get("/api/v1/projects/{pid}/evidence")
def list_evidence(pid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if not can_view(u,p): raise HTTPException(403,"Forbidden")
    return [{"id":e.id,"project_id":e.project_id,"title":e.title,"category":e.category,"description":e.description,"status":e.status,"filename":e.filename,"size_bytes":e.size_bytes,"content_type":e.content_type,"sha256":e.sha256,"reviewer_notes":e.reviewer_notes,"submitted_by":e.submitted_by,"created_at":e.created_at.isoformat()} for e in db.query(Evidence).filter_by(project_id=pid).order_by(Evidence.id.desc()).all()]

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
    if not p: raise HTTPException(404,"Project missing")
    if not can_view(u,p) and e.submitted_by!=u.id: raise HTTPException(403,"Forbidden")
    path=pathlib.Path(settings.upload_dir,e.stored_name).resolve()
    root=pathlib.Path(settings.upload_dir).resolve()
    if not str(path).startswith(str(root)) or not path.exists(): raise HTTPException(404,"File missing")  # path-traversal guard
    return FileResponse(path,filename=e.filename or "evidence",media_type=e.content_type or "application/octet-stream")

class ObservationIn(BaseModel): kind:str; note:str; latitude:Optional[float]=None; longitude:Optional[float]=None; observed_on:str=""
OBSERVATION_KINDS=("wildlife_sighting","water_quality","vegetation","erosion","community_feedback","other")

@app.post("/api/v1/projects/{pid}/observations",status_code=201)
def add_observation(pid:int,data:ObservationIn,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if u.role in ("buyer",): raise HTTPException(403,"Not permitted")
    if data.kind not in OBSERVATION_KINDS: raise HTTPException(400,"invalid kind")
    if not data.note.strip(): raise HTTPException(400,"note required")
    if (data.latitude is None)!=(data.longitude is None): raise HTTPException(422,"lat/lon must be provided together")
    if data.latitude is not None and not (-90<=data.latitude<=90 and -180<=data.longitude<=180): raise HTTPException(422,"coordinates out of range")
    o=Observation(project_id=pid,observer_id=u.id,**data.model_dump())
    db.add(o); db.flush(); audit(db,u,"observation.create","observation",o.id,{"project_id":pid}); db.commit(); db.refresh(o)
    return {"id":o.id,"kind":o.kind,"note":o.note,"status":o.status,"created_at":o.created_at.isoformat()}

@app.get("/api/v1/projects/{pid}/observations")
def list_observations(pid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if not can_view(u,p): raise HTTPException(403,"Forbidden")
    return [{"id":o.id,"kind":o.kind,"note":o.note,"latitude":float(o.latitude) if o.latitude is not None else None,"longitude":float(o.longitude) if o.longitude is not None else None,"observed_on":o.observed_on,"status":o.status,"observer_id":o.observer_id,"created_at":o.created_at.isoformat()} for o in db.query(Observation).filter_by(project_id=pid).order_by(Observation.id.desc()).all()]

REVIEW_CHECKLIST_DEFAULT=["boundary_and_area_reviewed","methodology_reference_valid","required_evidence_present","calculation_inputs_consistent","risk_assessment_noted"]

@app.get("/api/v1/projects/{pid}/review-package")
def review_package(pid:int,db:Session=Depends(get_db),u:User=Depends(require("verifier","admin"))):
    """Everything a reviewer needs: project, evidence statuses, latest calculation, prior decisions."""
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    ev=db.query(Evidence).filter_by(project_id=pid).all()
    last_calc=db.query(CalculationRun).filter_by(project_id=pid).order_by(CalculationRun.id.desc()).first()
    decs=db.query(VerificationDecision).filter_by(project_id=pid).order_by(VerificationDecision.id.desc()).all()
    return {"project":pub_project(p),
            "evidence":[{"id":e.id,"title":e.title,"category":e.category,"status":e.status,"has_file":bool(e.stored_name)} for e in ev],
            "missing_items":["at least one accepted evidence record"] if not any(e.status=="accepted" for e in ev) else [],
            "latest_calculation":{"id":last_calc.id,"result_tco2e":float(last_calc.result_tco2e),"methodology_version":last_calc.methodology_version,"inputs":last_calc.inputs,"warnings":last_calc.warnings} if last_calc else None,
            "previous_decisions":[{"id":d.id,"decision":d.decision,"reason":d.reason,"reviewer_id":d.reviewer_id,"created_at":d.created_at.isoformat()} for d in decs],
            "checklist_template":REVIEW_CHECKLIST_DEFAULT}

@app.post("/api/v1/projects/{pid}/decisions")
def decide(pid:int,data:DecisionIn,db:Session=Depends(get_db),u:User=Depends(require("verifier","admin"))):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if data.decision not in ("approved","rejected"): raise HTTPException(400,"decision must be approved/rejected")
    if not data.reason.strip(): raise HTTPException(400,"Reason required")
    if p.status not in ("under_review","submitted"): raise HTTPException(400,"Project is not under review")
    if p.status=="submitted": p.status="under_review"  # reviewers pick up submitted projects automatically
    if data.decision=="approved" and not db.query(Evidence).filter_by(project_id=pid,status="accepted").first():
        raise HTTPException(400,"Approval requires at least one accepted evidence record")
    d=VerificationDecision(project_id=pid,reviewer_id=u.id,decision=data.decision,reason=data.reason,checklist=data.checklist); p.status=data.decision
    if data.decision=="approved": p.data_quality="current"
    db.add(d); audit(db,u,"verification.decision","project",pid,{"decision":data.decision}); db.commit(); db.refresh(d)
    return {"id":d.id,"decision":d.decision,"project_status":p.status,"note":"Internal technical review decision — not independent third-party certification."}

@app.get("/api/v1/projects/{pid}/decisions")
def decisions(pid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if not can_view(u,p): raise HTTPException(403,"Forbidden")
    return [{"id":d.id,"decision":d.decision,"reason":d.reason,"reviewer_id":d.reviewer_id,"checklist":d.checklist,"created_at":d.created_at.isoformat()} for d in db.query(VerificationDecision).filter_by(project_id=pid).order_by(VerificationDecision.id.desc()).all()]

@app.post("/api/v1/projects/{pid}/calculations",status_code=201)
def run_calc(pid:int,data:CalcIn,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if not (can_edit(u,p) or u.role in ("verifier","admin")): raise HTTPException(403,"Only project owner/admin can run calculations")
    try: r=calculate(Decimal(str(p.area_ha)),p.ecosystem,p.reporting_years,Decimal(str(data.uncertainty)),Decimal(str(data.baseline_tco2e)))
    except ValueError as e: raise HTTPException(422,str(e))
    inputs={"area_ha":float(p.area_ha),"ecosystem":p.ecosystem,"years":p.reporting_years,"uncertainty":data.uncertainty,"baseline_tco2e":data.baseline_tco2e}
    run=CalculationRun(project_id=pid,created_by=u.id,methodology_version=r["methodology_version"],inputs=inputs,result_tco2e=r["result_tco2e"],gross_tco2e=r["gross_tco2e"],steps=r["steps"],warnings=r["warnings"])
    db.add(run); db.flush()
    p.data_quality="current"  # fresh run supersedes stale flag
    audit(db,u,"calculation.run","calculation",run.id,{"project_id":pid}); db.commit(); db.refresh(run)
    return {"id":run.id,"project_id":pid,"result_tco2e":float(run.result_tco2e),"gross_tco2e":float(run.gross_tco2e),"inputs":inputs,"steps":r["steps"],"warnings":r["warnings"],"methodology_version":run.methodology_version,"created_by":run.created_by,"created_at":run.created_at.isoformat()}

@app.get("/api/v1/projects/{pid}/calculations")
def list_calc(pid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    p=db.get(Project,pid)
    if not p: raise HTTPException(404,"Project not found")
    if not can_view(u,p): raise HTTPException(403,"Forbidden")
    return [{"id":r.id,"result_tco2e":float(r.result_tco2e),"gross_tco2e":float(r.gross_tco2e),"inputs":r.inputs,"steps":r.steps,"warnings":r.warnings,"methodology_version":r.methodology_version,"created_by":r.created_by,"created_at":r.created_at.isoformat()} for r in db.query(CalculationRun).filter_by(project_id=pid).order_by(CalculationRun.id.desc()).all()]

@app.get("/api/v1/calculations/{cid}")
def get_calc(cid:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    r=db.get(CalculationRun,cid)
    if not r: raise HTTPException(404,"not found")
    p=db.get(Project,r.project_id)
    if not can_view(u,p): raise HTTPException(403,"Forbidden")
    issued=db.query(CreditBatch).filter_by(calculation_id=cid).first()
    return {"id":r.id,"project_id":r.project_id,"result_tco2e":float(r.result_tco2e),"gross_tco2e":float(r.gross_tco2e),"inputs":r.inputs,"steps":r.steps,"warnings":r.warnings,"methodology_version":r.methodology_version,"created_by":r.created_by,"created_at":r.created_at.isoformat(),"issued_batch_id":issued.id if issued else None}

@app.post("/api/v1/credits/issue",status_code=201)
def issue(data:IssueIn,db:Session=Depends(get_db),u:User=Depends(require("verifier","admin"))):
    calc=db.get(CalculationRun,data.calculation_id)
    if not calc: raise HTTPException(404,"calculation not found")
    p=db.get(Project,calc.project_id)
    if p.status!="approved": raise HTTPException(400,"Issuance requires an approved project (workflow prerequisite)")
    if p.data_quality=="stale": raise HTTPException(400,"Project data changed after calculation; recalculate before issuance")
    latest=db.query(CalculationRun).filter_by(project_id=p.id).order_by(CalculationRun.id.desc()).first()
    if latest.id!=calc.id: raise HTTPException(400,"Stale calculation: issuance must reference the latest calculation run")
    q=Decimal(str(data.quantity))
    if q<=0: raise HTTPException(400,"quantity must be positive")
    if q>Decimal(str(calc.result_tco2e)): raise HTTPException(400,f"Quantity exceeds eligible calculated quantity ({float(calc.result_tco2e)} tCO2e)")
    already=db.query(func.coalesce(func.sum(CreditBatch.quantity),0)).filter_by(calculation_id=calc.id).scalar()
    if Decimal(str(already))+q>Decimal(str(calc.result_tco2e)): raise HTTPException(409,"Same eligible quantity cannot be issued twice (batch total would exceed calculation)")
    b=CreditBatch(serial=f"BCA-DEMO-{calc.project_id}-{calc.id}-{uuid.uuid4().hex[:6].upper()}",project_id=p.id,calculation_id=calc.id,quantity=q,available=q,issued_by=u.id)
    db.add(b)
    try:
        db.flush()
        audit(db,u,"credit.issue","credit_batch",b.id,{"quantity":float(q),"calculation_id":calc.id,"label":"simulated"})
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,"Duplicate issuance prevented")
    db.refresh(b)
    return {"id":b.id,"serial":b.serial,"quantity":float(b.quantity),"available":float(b.available),"calculation_id":b.calculation_id,"project_id":b.project_id,"label":"Simulated demonstration credits — not externally verified or tradable"}

@app.get("/api/v1/credits")
def credits(db:Session=Depends(get_db),u:User=Depends(get_current_user),skip:int=0,limit:int=Query(100,le=200)):
    qy=db.query(CreditBatch).order_by(CreditBatch.id.desc()); total=qy.count()
    return {"items":[{"id":b.id,"serial":b.serial,"project_id":b.project_id,"calculation_id":b.calculation_id,"quantity":float(b.quantity),"available":float(b.available),"sold":float(b.sold),"retired":float(b.retired),"status":b.status,"issued_by":b.issued_by,"created_at":b.created_at.isoformat()} for b in qy.offset(skip).limit(limit).all()],"total":total}

@app.post("/api/v1/credits/{bid}/retire")
def retire(bid:int,quantity:float=Form(...),reason:str=Form(""),db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    b=db.get(CreditBatch,bid)
    if not b: raise HTTPException(404,"batch not found")
    owns_project=db.query(Project).filter_by(id=b.project_id,owner_id=u.id).first() is not None
    holds_credit=db.query(Order).join(Listing,Order.listing_id==Listing.id).filter(Listing.batch_id==bid,Order.buyer_id==u.id).first() is not None
    if u.role!="admin" and not owns_project and not holds_credit:
        raise HTTPException(403,"Only the project owner, a purchaser holding credits from this batch, or an administrator may retire")
    q=Decimal(str(quantity))
    if q<=0: raise HTTPException(400,"Retirement quantity must be positive")
    # Conditional atomic update prevents concurrent double-retirement race.
    upd=db.query(CreditBatch).filter(CreditBatch.id==bid, CreditBatch.available>=q).update(
        {"available":CreditBatch.available-q,"retired":CreditBatch.retired+q}, synchronize_session=False)
    if not upd: db.rollback(); raise HTTPException(400,"Invalid retirement quantity (insufficient available)")
    db.expire(b)
    if b.available==0: b.status="fully_retired"
    audit(db,u,"credit.retire","credit_batch",bid,{"quantity":float(q),"reason":reason}); db.commit()
    return {"id":b.id,"retired":float(b.retired),"available":float(b.available),"note":"Retirement recorded locally in the demo registry only."}

@app.get("/api/v1/listings")
def listings(db:Session=Depends(get_db),u:User=Depends(get_current_user),q:str="",ecosystem:Optional[str]=None,skip:int=0,limit:int=Query(50,le=200)):
    """Public marketplace browse (auth required to prevent scraping; all listed credits are simulated demo inventory)."""
    from sqlalchemy import func as _func
    rows=db.query(Listing).join(CreditBatch,Listing.batch_id==CreditBatch.id).join(Project,CreditBatch.project_id==Project.id).filter(Listing.status=="active")
    if q: rows=rows.filter(Project.name.ilike(f"%{q}%")|Listing.title.ilike(f"%{q}%"))
    if ecosystem: rows=rows.filter(Project.ecosystem==ecosystem)
    total=rows.count()
    items=[]
    for l,b,p in rows.with_entities(Listing,CreditBatch,Project).order_by(Listing.id.desc()).offset(skip).limit(limit).all():
        items.append({"id":l.id,"title":l.title,"price_usd":float(l.price_usd),"currency":"USD","quantity":float(b.quantity),"available":float(l.available),"batch_id":l.batch_id,"batch_serial":b.serial,"project_name":p.name,"ecosystem":p.ecosystem,"project_id":p.id,"seller_id":l.seller_id,"status":l.status,"verification_status":"internally approved (not third-party certified)","note":"Simulated demo credits"})
    return {"items":items,"total":total}
@app.post("/api/v1/listings",status_code=201)
def create_listing(data:ListingIn,db:Session=Depends(get_db),u:User=Depends(require("developer","admin"))):
    b=db.get(CreditBatch,data.batch_id)
    if not b: raise HTTPException(404,"batch not found")
    p=db.get(Project,b.project_id)
    if u.role!="admin" and p.owner_id!=u.id: raise HTTPException(403,"Only project owner can list its credits")
    if b.status not in ("issued","partially_sold"): raise HTTPException(400,"Batch is not listable")
    if data.quantity<=0 or Decimal(str(data.quantity))>Decimal(str(b.available)): raise HTTPException(400,"Quantity exceeds available credits")
    if data.price_usd<=0: raise HTTPException(400,"price_usd must be positive")
    l=Listing(batch_id=b.id,seller_id=u.id,title=data.title,price_usd=Decimal(str(data.price_usd)),quantity=data.quantity,available=data.quantity); db.add(l); db.flush()
    b.status="listed"
    audit(db,u,"listing.create","listing",l.id,{"batch_id":b.id,"quantity":data.quantity}); db.commit(); db.refresh(l)
    return {"id":l.id,"available":float(l.available),"note":"Demo listing of simulated credits"}
@app.post("/api/v1/listings/{lid}/purchase",status_code=201)
def purchase(lid:int,data:OrderIn,db:Session=Depends(get_db),u:User=Depends(require("buyer","admin"))):
    if data.idempotency_key and db.query(Order).filter_by(idempotency_key=data.idempotency_key).first(): raise HTTPException(409,"Duplicate purchase submission prevented")
    l=db.query(Listing).filter_by(id=lid).with_for_update().first()
    if not l or l.status!="active": raise HTTPException(400,"Listing not active")
    if data.quantity<=0: raise HTTPException(400,"quantity must be positive")
    qty=Decimal(str(data.quantity))
    if qty>Decimal(str(l.available)): raise HTTPException(400,"Insufficient available quantity")
    total=(qty*Decimal(str(l.price_usd))).quantize(Decimal("0.01"))
    # Atomic: decrement listing + batch inventory and insert order in ONE transaction.
    l.available=Decimal(str(l.available))-qty
    b=db.get(CreditBatch,l.batch_id); b.available=Decimal(str(b.available))-qty; b.sold=Decimal(str(b.sold))+qty
    if b.available==0: b.status="fully_sold"
    o=Order(listing_id=lid,buyer_id=u.id,quantity=qty,unit_price=l.price_usd,total_usd=total,idempotency_key=data.idempotency_key); db.add(o)
    audit(db,u,"order.purchase","order",None,{"listing_id":lid,"quantity":float(qty),"note":"simulated, no real payment"})
    try:
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,"Duplicate purchase submission prevented")
    db.refresh(o)
    return {"id":o.id,"total_usd":float(o.total_usd),"quantity":float(o.quantity),"status":o.status,"note":"Simulated demo purchase - no real payment processed"}
@app.get("/api/v1/orders")
def orders(db:Session=Depends(get_db),u:User=Depends(get_current_user),skip:int=0,limit:int=Query(100,le=200)):
    q=db.query(Order)
    if u.role=="buyer": q=q.filter_by(buyer_id=u.id)
    elif u.role!="admin":
        my_listings=[l.id for l in db.query(Listing).filter_by(seller_id=u.id).all()]
        q=q.filter((Order.buyer_id==u.id)|(Order.listing_id.in_(my_listings)))
    total=q.count()
    return {"items":[{"id":o.id,"listing_id":o.listing_id,"buyer_id":o.buyer_id,"quantity":float(o.quantity),"unit_price":float(o.unit_price),"total_usd":float(o.total_usd),"status":o.status,"created_at":o.created_at.isoformat()} for o in q.order_by(Order.id.desc()).offset(skip).limit(limit).all()],"total":total}

@app.get("/api/v1/dashboard")
def dashboard(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    q=db.query(Project)
    if u.role=="developer": q=q.filter_by(owner_id=u.id)
    projects=q.all()
    projects.sort(key=lambda p: p.id, reverse=True)
    def c(s): return sum(1 for p in projects if p.status==s)
    eco={}
    for p in projects: eco[p.ecosystem]=eco.get(p.ecosystem,0)+1
    batches=db.query(CreditBatch).all(); listings=db.query(Listing).filter_by(status="active").all()
    my_ids={p.id for p in projects}
    evq=db.query(Evidence).filter_by(status="pending")
    cq=db.query(CalculationRun)
    if u.role=="developer":
        evq=evq.filter(Evidence.project_id.in_(my_ids or {-1})); cq=cq.filter(CalculationRun.project_id.in_(my_ids or {-1}))
    elif u.role not in ("admin","verifier"):
        evq=evq.filter(Evidence.submitted_by==u.id); cq=cq.filter(CalculationRun.created_by==u.id)
    return {"role":u.role,"total_projects":len(projects),"draft":c("draft"),"submitted":c("submitted"),"under_review":c("under_review"),"approved":c("approved"),"rejected":c("rejected"),"evidence_pending":evq.count(),"calculations":cq.count(),"potential_tco2e":float(sum(Decimal(str(r.result_tco2e)) for r in db.query(CalculationRun).all())),"issued_credits":float(sum(Decimal(str(b.quantity)) for b in batches)),"available_credits":float(sum(Decimal(str(b.available)) for b in batches)),"active_listings":len(listings),"ecosystem_distribution":eco,"recent_projects":[pub_project(p) for p in projects[:5]]}
@app.get("/api/v1/audit")
def audit_list(db:Session=Depends(get_db),u:User=Depends(require("admin","verifier"))):
    return [{"id":a.id,"actor_id":a.actor_id,"action":a.action,"resource_type":a.resource_type,"resource_id":a.resource_id,"meta":a.meta,"created_at":a.created_at.isoformat()} for a in db.query(AuditLog).order_by(AuditLog.id.desc()).limit(200).all()]
