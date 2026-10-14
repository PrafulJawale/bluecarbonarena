# Database Schema
Users, Projects, Evidence, VerificationDecisions, CalculationRuns, CreditBatches (unique calculation_id prevents duplicate issuance), Listings, Orders (unique idempotency_key), AuditLogs. Timestamps timezone-aware, Decimal/Numeric for money & carbon. See `backend/app/models.py`.
