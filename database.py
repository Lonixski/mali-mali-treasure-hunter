import os
import re
from dotenv import load_dotenv

load_dotenv()

from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, BigInteger, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("FATAL: DATABASE_URL environment variable is not set.")

DATABASE_URL = re.sub(r'^postgresql\+[^:]+://', 'postgresql://', DATABASE_URL)
DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

if "sslmode=" not in DATABASE_URL:
    if "?" in DATABASE_URL:
        DATABASE_URL += "&sslmode=require"
    else:
        DATABASE_URL += "?sslmode=require"

connect_args = {"connect_timeout": 30}

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args=connect_args
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Site(Base):
    __tablename__ = "sites"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    url = Column(String, nullable=False)
    product_selector = Column(String, nullable=True)
    title_selector = Column(String, nullable=True)
    price_selector = Column(String, nullable=True)
    link_selector = Column(String, nullable=True)
    affiliate_link = Column(String, nullable=True)
    deals = relationship("Deal", back_populates="site", cascade="all, delete-orphan")

class Deal(Base):
    __tablename__ = "deals"
    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    title = Column(String, nullable=False)
    url = Column(String, nullable=False, unique=True)
    image_url = Column(String, nullable=True)
    original_price = Column(Float, nullable=True)
    current_price = Column(Float, nullable=False)
    category = Column(String, nullable=True)
    is_expired = Column(Boolean, default=False)
    telegram_message_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    site = relationship("Site", back_populates="deals")
    snapshots = relationship("PriceSnapshot", back_populates="deal", cascade="all, delete-orphan")

class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    id = Column(Integer, primary_key=True, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=False)
    price = Column(Float, nullable=False)
    checked_at = Column(DateTime, default=datetime.utcnow)
    deal = relationship("Deal", back_populates="snapshots")

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()