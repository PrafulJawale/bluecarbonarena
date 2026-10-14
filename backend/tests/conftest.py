"""Pytest fixtures: isolated in-memory SQLite database per test session.

Never touches the development database (bluecarbon.db) or production data.
"""
import os, sys, pathlib

# Must be set BEFORE importing app modules so config/engine pick it up.
os.environ["DATABASE_URL"] = "sqlite:///./test_bca.db"
os.environ["SECRET_KEY"] = "test-secret-key-only-for-pytests-0123456789"
os.environ["DEMO_MODE"] = "true"
os.environ["RATE_LIMIT_ENABLED"] = "false"  # keep integration tests deterministic; rate limiting itself is verified separately
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Base, engine, SessionLocal
from app.models import User, Project, CreditBatch, Listing, Order
from app.security import hash_pw


@pytest.fixture(scope="session", autouse=True)
def _database():
    # Remove leftover test DB, create a fresh schema (test-only file).
    path = pathlib.Path("./test_bca.db")
    if path.exists():
        path.unlink()
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if path.exists():
        path.unlink()


@pytest.fixture()
def db() -> Session:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def client() -> TestClient:
    from app.main import app
    return TestClient(app)


ROLE_PASSWORD = "Password123!"


def _make_user(db: Session, email: str, role: str) -> User:
    u = db.query(User).filter_by(email=email).first()
    if not u:
        u = User(email=email, full_name=f"Test {role}",
                 hashed_password=hash_pw(ROLE_PASSWORD), role=role)
        db.add(u)
        db.commit()
        db.refresh(u)
    elif u.role != role:
        u.role = role
        db.commit()
    return u


@pytest.fixture()
def tokens(client, db):
    """Return dict role -> bearer token for all six roles."""
    out = {}
    for role in ("admin", "verifier", "developer", "researcher", "buyer", "community"):
        email = f"{role}@test.local"
        _make_user(db, email, role)
        r = client.post("/api/v1/auth/login",
                        json={"email": email, "password": ROLE_PASSWORD})
        assert r.status_code == 200, r.text
        out[role] = r.json()["access_token"]
    return out


def auth(tok: str):
    return {"Authorization": f"Bearer {tok}"}
