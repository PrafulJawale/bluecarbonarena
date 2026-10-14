from app.db import Base,engine
from app import models
target_metadata=Base.metadata
# Production: use `alembic revision --autogenerate` then `alembic upgrade head`. Initial schema is also created by this migration baseline.
