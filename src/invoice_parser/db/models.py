import sqlalchemy as sa
from sqlalchemy import Column, Text, Integer, Numeric, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# §5 — api_keys table
class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(Text, primary_key=True)
    hashed_key = Column(Text, nullable=False, unique=True)
    name = Column(Text, nullable=False)
    rate_limit_per_minute = Column(Integer, server_default="60")
    monthly_cost_cap_usd = Column(Numeric(10, 2))
    created_at = Column(TIMESTAMP(timezone=True), server_default=sa.text("now()"))
    revoked_at = Column(TIMESTAMP(timezone=True))


# §5 — jobs table
class Job(Base):
    __tablename__ = "jobs"

    id = Column(Text, primary_key=True)
    api_key_id = Column(Text, ForeignKey("api_keys.id"), nullable=False)
    status = Column(Text, nullable=False)
    input_source = Column(Text, nullable=False)
    input_manifest = Column(JSONB, nullable=False)
    output_format = Column(Text, nullable=False)
    file_count = Column(Integer)
    files_completed = Column(Integer, server_default="0")
    files_failed = Column(Integer, server_default="0")
    invoices_extracted = Column(Integer, server_default="0")
    invoices_review = Column(Integer, server_default="0")
    result_xlsx_key = Column(Text)
    result_json_key = Column(Text)
    cost_usd = Column(Numeric(10, 4), server_default="0")
    created_at = Column(TIMESTAMP(timezone=True), server_default=sa.text("now()"))
    started_at = Column(TIMESTAMP(timezone=True))
    finished_at = Column(TIMESTAMP(timezone=True))
    expires_at = Column(TIMESTAMP(timezone=True))
    error = Column(Text)


# §5 — invoices table
class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Text, primary_key=True)
    job_id = Column(Text, ForeignKey("jobs.id"), nullable=False)
    source_file = Column(Text, nullable=False)
    source_pages = Column(ARRAY(Integer))
    invoice_index_in_file = Column(Integer, server_default="1")
    status = Column(Text, nullable=False)
    notes = Column(Text)
    cost_usd = Column(Numeric(10, 4))
    models_used = Column(ARRAY(Text))
    extracted = Column(JSONB, nullable=False)
    audit = Column(JSONB, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=sa.text("now()"))
