"""API integration tests (isolated test database via conftest fixtures).

Covers: auth flow, role enforcement, cross-user access prevention, project
lifecycle state machine, evidence, verification decisions, calculations,
issuance prerequisites + duplicate prevention, marketplace atomicity,
dashboard aggregation, audit log authorization.
"""
import pytest


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def dev_project(client, tokens):
    """A draft mangrove project owned by the developer."""
    r = client.post("/api/v1/projects", headers=H(tokens["developer"]), json={
        "name": "API Test Mangrove", "ecosystem": "mangrove", "area_ha": 100,
        "region": "Test Coast", "latitude": 19.0, "longitude": 72.8})
    assert r.status_code == 201, r.text
    return r.json()


def test_health_and_me(client, tokens):
    assert client.get("/api/v1/health").status_code == 200
    me = client.get("/api/v1/auth/me", headers=H(tokens["admin"]))
    assert me.status_code == 200 and me.json()["role"] == "admin"


def test_login_invalid_and_unauthenticated(client):
    r = client.post("/api/v1/auth/login", json={"email": "nope@x.local", "password": "Whatever123!"})
    assert r.status_code == 401
    assert "Invalid email or password" in r.json()["detail"]
    assert client.get("/api/v1/projects").status_code == 401
    assert client.get("/api/v1/projects", headers=H("garbage")).status_code == 401


def test_logout_invalidates_session(client, tokens):
    tok = tokens["community"]
    assert client.get("/api/v1/auth/me", headers=H(tok)).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=H(tok)).status_code == 200
    # server-side revocation: previous token must now fail
    assert client.get("/api/v1/auth/me", headers=H(tok)).status_code == 401


def test_registration_role_restriction(client):
    r = client.post("/api/v1/auth/register", json={"email": "sneaky@t.local", "password": "Password123!", "role": "admin"})
    assert r.status_code == 400  # cannot self-assign privileged roles


def test_project_lifecycle_and_cross_user(client, tokens, dev_project):
    pid = dev_project["id"]
    hdev, hbuyer, hadm = H(tokens["developer"]), H(tokens["buyer"]), H(tokens["admin"])
    # buyer can view public-ish project but not edit
    assert client.put(f"/api/v1/projects/{pid}", headers=H(tokens["researcher"]),
                      json={"name": "x", "ecosystem": "mangrove", "area_ha": 1}).status_code == 403
    # invalid transition: draft -> approved is impossible via button
    assert client.post(f"/api/v1/projects/{pid}/transition?new_status=approved", headers=hdev).status_code == 400
    # valid: draft -> submitted
    assert client.post(f"/api/v1/projects/{pid}/transition?new_status=submitted", headers=hdev).status_code == 200
    # editing while under review blocked
    assert client.put(f"/api/v1/projects/{pid}", headers=hdev,
                      json={"name": "y", "ecosystem": "mangrove", "area_ha": 1}).status_code == 400


def test_evidence_submission_and_review(client, tokens, dev_project):
    pid = dev_project["id"]
    # researcher must first be added as a project member by the owner
    users = client.get("/api/v1/users", headers=H(tokens["admin"])).json()["items"]
    rid = [u for u in users if u["role"] == "researcher"][0]["id"]
    assert client.post(f"/api/v1/projects/{pid}/members", headers=H(tokens["developer"]),
                       json={"user_id": rid, "role": "collaborator"}).status_code == 201
    files = {"file": ("note.txt", b"demo field note", "text/plain")}
    r = client.post(f"/api/v1/projects/{pid}/evidence", headers=H(tokens["researcher"]),
                    data={"title": "Field note", "category": "site_survey"}, files=files)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    # buyer may not submit evidence at all
    rb = client.post(f"/api/v1/projects/{pid}/evidence", headers=H(tokens["buyer"]),
                     data={"title": "x", "category": "site_survey"})
    assert rb.status_code == 403
    # only verifier/admin can review
    assert client.patch(f"/api/v1/evidence/{eid}/review?status=accepted", headers=H(tokens["developer"])).status_code == 403
    assert client.patch(f"/api/v1/evidence/{eid}/review?status=accepted", headers=H(tokens["verifier"])).status_code == 200
    # download authorized
    dl = client.get(f"/api/v1/evidence/{eid}/download", headers=H(tokens["developer"]))
    assert dl.status_code == 200 and dl.content == b"demo field note"


def test_bad_file_content_rejected(client, tokens, dev_project):
    pid = dev_project["id"]
    client.post(f"/api/v1/projects/{pid}/members", headers=H(tokens["developer"]),
                json={"user_id": [u for u in client.get("/api/v1/users", headers=H(tokens["admin"])).json()["items"] if u["role"]=="researcher"][0]["id"]})
    # declare png but send jpeg magic mismatched content type claim
    files = {"file": ("fake.png", bytes([0x89,0x50,0x4E,0x47])+b"truncated-not-really-png", "application/pdf")}
    r = client.post(f"/api/v1/projects/{pid}/evidence", headers=H(tokens["researcher"]),
                    data={"title": "exe disguised", "category": "field_photo"}, files=files)
    assert r.status_code == 400  # declared png but content isn't png/pdf/jpeg and type not allowed


def test_verification_decision_requires_evidence(client, tokens, dev_project):
    pid = dev_project["id"]
    hv = H(tokens["verifier"])
    client.post(f"/api/v1/projects/{pid}/transition?new_status=submitted", headers=H(tokens["developer"]))
    # approve without accepted evidence -> rejected by backend
    r = client.post(f"/api/v1/projects/{pid}/decisions", headers=hv,
                    json={"decision": "approved", "reason": "looks fine"})
    assert r.status_code == 400
    # developer cannot record decisions
    assert client.post(f"/api/v1/projects/{pid}/decisions", headers=H(tokens["developer"]),
                       json={"decision": "approved", "reason": "self approve"}).status_code == 403


def _approve(client, tokens, pid):
    files = {"file": ("ev.txt", b"evidence body", "text/plain")}
    e = client.post(f"/api/v1/projects/{pid}/evidence", headers=H(tokens["developer"]),
                    data={"title": "Survey", "category": "site_survey"}, files=files)
    client.patch(f"/api/v1/evidence/{e.json()['id']}/review?status=accepted", headers=H(tokens["verifier"]))
    client.post(f"/api/v1/projects/{pid}/transition?new_status=submitted", headers=H(tokens["developer"]))
    d = client.post(f"/api/v1/projects/{pid}/decisions", headers=H(tokens["verifier"]),
                    json={"decision": "approved", "reason": "Documentation complete."})
    assert d.status_code == 200, d.text
    return d.json()


def test_calculation_deterministic_and_persisted(client, tokens, dev_project):
    pid = dev_project["id"]
    h = H(tokens["developer"])
    c1 = client.post(f"/api/v1/projects/{pid}/calculations", headers=h, json={"uncertainty": 0.1}).json()
    c2 = client.post(f"/api/v1/projects/{pid}/calculations", headers=h, json={"uncertainty": 0.1}).json()
    assert c1["result_tco2e"] == c2["result_tco2e"] == 9900.0  # 100 ha x 6 tC/ha/yr x 5 yr x 44/12 = 11000 gross; x0.9 = 9900
    bad = client.post(f"/api/v1/projects/{pid}/calculations", headers=h, json={"uncertainty": 1.5})
    assert bad.status_code == 422


def test_issuance_rules(client, tokens, dev_project):
    pid = dev_project["id"]
    hdev, hver = H(tokens["developer"]), H(tokens["verifier"])
    calc = client.post(f"/api/v1/projects/{pid}/calculations", headers=hdev, json={}).json()
    # developer cannot issue
    assert client.post("/api/v1/credits/issue", headers=hdev,
                       json={"calculation_id": calc["id"], "quantity": 10}).status_code == 403
    # unapproved project cannot be issued against
    r = client.post("/api/v1/credits/issue", headers=hver,
                    json={"calculation_id": calc["id"], "quantity": 10})
    assert r.status_code == 400
    # approve then issue
    _approve(client, tokens, pid)
    calc2 = client.post(f"/api/v1/projects/{pid}/calculations", headers=hver, json={}).json()
    over = client.post("/api/v1/credits/issue", headers=hver,
                       json={"calculation_id": calc2["id"], "quantity": 999999})
    assert over.status_code == 400  # exceeds eligible quantity
    ok = client.post("/api/v1/credits/issue", headers=hver,
                     json={"calculation_id": calc2["id"], "quantity": 1000})
    assert ok.status_code == 201, ok.text
    dup = client.post("/api/v1/credits/issue", headers=hver,
                      json={"calculation_id": calc2["id"], "quantity": 999999})
    assert dup.status_code in (400, 409)  # cannot double-issue beyond eligible quantity


def test_marketplace_purchase_and_inventory(client, tokens, dev_project):
    pid = dev_project["id"]
    hdev, hver, hbuy = H(tokens["developer"]), H(tokens["verifier"]), H(tokens["buyer"])
    _approve(client, tokens, pid)
    calc = client.post(f"/api/v1/projects/{pid}/calculations", headers=hver, json={}).json()
    b = client.post("/api/v1/credits/issue", headers=hver,
                    json={"calculation_id": calc["id"], "quantity": 100})
    assert b.status_code == 201
    bid = b.json()["id"]
    l = client.post("/api/v1/listings", headers=hdev,
                    json={"batch_id": bid, "title": "Test credits", "price_usd": 10.00, "quantity": 100})
    assert l.status_code == 201, l.text
    lid = l.json()["id"]
    # non-buyer cannot purchase
    assert client.post(f"/api/v1/listings/{lid}/purchase", headers=hdev,
                       json={"quantity": 10}).status_code == 403
    o = client.post(f"/api/v1/listings/{lid}/purchase", headers=hbuy,
                    json={"quantity": 40, "idempotency_key": "k1"})
    assert o.status_code == 201 and o.json()["total_usd"] == 400.0
    # duplicate idempotency key prevented
    assert client.post(f"/api/v1/listings/{lid}/purchase", headers=hbuy,
                       json={"quantity": 40, "idempotency_key": "k1"}).status_code == 409
    # oversell prevented
    assert client.post(f"/api/v1/listings/{lid}/purchase", headers=hbuy,
                       json={"quantity": 61}).status_code == 400
    # inventory consistent: available 60 on listing & batch
    ls = [x for x in client.get("/api/v1/listings", headers=hbuy).json()["items"] if x["id"] == lid][0]
    assert ls["available"] == 60
    bat = [x for x in client.get("/api/v1/credits", headers=hbuy).json()["items"] if x["id"] == bid][0]
    assert bat["sold"] == 40 and bat["available"] == 60


def test_dashboard_metrics_real(client, tokens, dev_project):
    d = client.get("/api/v1/dashboard", headers=H(tokens["developer"])).json()
    assert d["total_projects"] >= 1
    assert isinstance(d["issued_credits"], float)
    # admin sees everything
    da = client.get("/api/v1/dashboard", headers=H(tokens["admin"])).json()
    assert da["total_projects"] >= d["total_projects"]


def test_audit_requires_privilege(client, tokens):
    assert client.get("/api/v1/audit", headers=H(tokens["buyer"])).status_code == 403
    a = client.get("/api/v1/audit", headers=H(tokens["admin"]))
    assert a.status_code == 200 and len(a.json()) > 0


def test_admin_user_management(client, tokens):
    users = client.get("/api/v1/users", headers=H(tokens["admin"])).json()
    target = [u for u in users["items"] if u["role"] == "community"][0]
    r = client.patch(f"/api/v1/users/{target['id']}/active", headers=H(tokens["admin"]),
                     json={"is_active": False})
    assert r.status_code == 200
    # non-admin forbidden
    assert client.get("/api/v1/users", headers=H(tokens["buyer"])).status_code == 403
