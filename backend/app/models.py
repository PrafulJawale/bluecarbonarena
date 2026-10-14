
from sqlalchemy import String,Integer,ForeignKey,DateTime,Text,Boolean,Numeric,JSON,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column,relationship
from datetime import datetime,timezone
from .db import Base
def now(): return datetime.now(timezone.utc)
class ProjectMember(Base):
    __tablename__="project_members"
    id:Mapped[int]=mapped_column(primary_key=True); project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True); user_id:Mapped[int]=mapped_column(ForeignKey("users.id"),index=True)
    role:Mapped[str]=mapped_column(String(30),default="collaborator")
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(UniqueConstraint("project_id","user_id",name="uq_project_member"),)
class Observation(Base):
    __tablename__="observations"
    id:Mapped[int]=mapped_column(primary_key=True); project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True); observer_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    kind:Mapped[str]=mapped_column(String(60)); note:Mapped[str]=mapped_column(Text); latitude:Mapped[float|None]=mapped_column(Numeric(10,6),nullable=True); longitude:Mapped[float|None]=mapped_column(Numeric(10,6),nullable=True)
    observed_on:Mapped[str]=mapped_column(String(20),default="")
    status:Mapped[str]=mapped_column(String(30),default="recorded"); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class User(Base):
    __tablename__="users"
    id:Mapped[int]=mapped_column(primary_key=True); email:Mapped[str]=mapped_column(String(255),unique=True,index=True); full_name:Mapped[str]=mapped_column(String(255))
    hashed_password:Mapped[str]=mapped_column(String(255)); role:Mapped[str]=mapped_column(String(50),index=True); is_active:Mapped[bool]=mapped_column(Boolean,default=True)
    token_version:Mapped[int]=mapped_column(Integer,default=0,nullable=False)  # bump to revoke all issued tokens (logout/deactivation/role change)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class Project(Base):
    __tablename__="projects"
    id:Mapped[int]=mapped_column(primary_key=True); name:Mapped[str]=mapped_column(String(255)); description:Mapped[str]=mapped_column(Text,default="")
    owner_id:Mapped[int]=mapped_column(ForeignKey("users.id"),index=True); country:Mapped[str]=mapped_column(String(120),default="India"); region:Mapped[str]=mapped_column(String(120),default="")
    ecosystem:Mapped[str]=mapped_column(String(50),index=True); area_ha:Mapped[float]=mapped_column(Numeric(14,4)); status:Mapped[str]=mapped_column(String(30),default="draft",index=True)
    start_date:Mapped[str]=mapped_column(String(20),default="2024-01-01"); reporting_years:Mapped[int]=mapped_column(Integer,default=5)
    methodology:Mapped[str]=mapped_column(String(120),default="BCA-ILLUSTRATIVE v1.0"); latitude:Mapped[float|None]=mapped_column(Numeric(10,6),nullable=True); longitude:Mapped[float|None]=mapped_column(Numeric(10,6),nullable=True)
    data_quality:Mapped[str]=mapped_column(String(30),default="current")  # current | stale (set when material edits invalidate calculations)
    boundary:Mapped[dict|None]=mapped_column(JSON,nullable=True); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now); updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
    owner=relationship("User")
class Evidence(Base):
    __tablename__="evidence"
    id:Mapped[int]=mapped_column(primary_key=True); project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True); submitted_by:Mapped[int]=mapped_column(ForeignKey("users.id"))
    title:Mapped[str]=mapped_column(String(255)); category:Mapped[str]=mapped_column(String(80)); description:Mapped[str]=mapped_column(Text,default="")
    filename:Mapped[str|None]=mapped_column(String(255),nullable=True); stored_name:Mapped[str|None]=mapped_column(String(255),nullable=True); content_type:Mapped[str|None]=mapped_column(String(120),nullable=True); size_bytes:Mapped[int|None]=mapped_column(Integer,nullable=True); sha256:Mapped[str|None]=mapped_column(String(64),nullable=True)
    status:Mapped[str]=mapped_column(String(30),default="pending"); reviewer_notes:Mapped[str]=mapped_column(Text,default=""); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class VerificationDecision(Base):
    __tablename__="verification_decisions"
    id:Mapped[int]=mapped_column(primary_key=True); project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True); reviewer_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    decision:Mapped[str]=mapped_column(String(30)); reason:Mapped[str]=mapped_column(Text); checklist:Mapped[dict|None]=mapped_column(JSON,nullable=True); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class CalculationRun(Base):
    __tablename__="calculation_runs"
    id:Mapped[int]=mapped_column(primary_key=True); project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True); created_by:Mapped[int]=mapped_column(ForeignKey("users.id"))
    methodology_version:Mapped[str]=mapped_column(String(50)); inputs:Mapped[dict]=mapped_column(JSON); result_tco2e:Mapped[float]=mapped_column(Numeric(16,4)); gross_tco2e:Mapped[float]=mapped_column(Numeric(16,4)); steps:Mapped[list]=mapped_column(JSON); warnings:Mapped[list]=mapped_column(JSON); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class CreditBatch(Base):
    __tablename__="credit_batches"; __table_args__=(UniqueConstraint("calculation_id",name="uq_calc_issuance"),)
    id:Mapped[int]=mapped_column(primary_key=True); serial:Mapped[str]=mapped_column(String(80),unique=True); project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True); calculation_id:Mapped[int]=mapped_column(ForeignKey("calculation_runs.id"),unique=True)
    quantity:Mapped[float]=mapped_column(Numeric(16,4)); available:Mapped[float]=mapped_column(Numeric(16,4)); sold:Mapped[float]=mapped_column(Numeric(16,4),default=0); retired:Mapped[float]=mapped_column(Numeric(16,4),default=0); status:Mapped[str]=mapped_column(String(30),default="issued"); issued_by:Mapped[int]=mapped_column(ForeignKey("users.id")); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class Listing(Base):
    __tablename__="listings"
    id:Mapped[int]=mapped_column(primary_key=True); batch_id:Mapped[int]=mapped_column(ForeignKey("credit_batches.id"),index=True); seller_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    title:Mapped[str]=mapped_column(String(255)); price_usd:Mapped[float]=mapped_column(Numeric(12,2)); quantity:Mapped[float]=mapped_column(Numeric(16,4)); available:Mapped[float]=mapped_column(Numeric(16,4)); status:Mapped[str]=mapped_column(String(30),default="active"); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class Order(Base):
    __tablename__="orders"
    id:Mapped[int]=mapped_column(primary_key=True); listing_id:Mapped[int]=mapped_column(ForeignKey("listings.id"),index=True); buyer_id:Mapped[int]=mapped_column(ForeignKey("users.id"),index=True)
    quantity:Mapped[float]=mapped_column(Numeric(16,4)); unit_price:Mapped[float]=mapped_column(Numeric(12,2)); total_usd:Mapped[float]=mapped_column(Numeric(14,2)); status:Mapped[str]=mapped_column(String(40),default="completed_simulated"); idempotency_key:Mapped[str|None]=mapped_column(String(120),nullable=True,unique=True); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class AuditLog(Base):
    __tablename__="audit_logs"
    id:Mapped[int]=mapped_column(primary_key=True); actor_id:Mapped[int|None]=mapped_column(Integer,nullable=True,index=True); action:Mapped[str]=mapped_column(String(120),index=True); resource_type:Mapped[str]=mapped_column(String(80)); resource_id:Mapped[str|None]=mapped_column(String(80),nullable=True); meta:Mapped[dict|None]=mapped_column(JSON,nullable=True); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
