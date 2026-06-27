import os
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Use PostgreSQL in cloud, SQLite locally
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./mali_mali.db")

# Fix SQLAlchemy URL format for Render
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Site(Base):
    __tablename__ = "sites"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    url = Column(String)
    product_selector = Column(String)
    title_selector = Column(String)
    price_selector = Column(String)
    link_selector = Column(String)
    affiliate_id = Column(String, nullable=True)

class Deal(Base):
    __tablename__ = "deals"
    id = Column(Integer, primary_key=True, index=True)
    store = Column(String, index=True)
    product = Column(String)
    price = Column(String)
    link = Column(String)
    discovered_at = Column(String)
    is_active = Column(Integer, default=1)

class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    id = Column(Integer, primary_key=True, index=True)
    store = Column(String, index=True)
    product = Column(String, index=True)
    price = Column(String)
    recorded_at = Column(String)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()