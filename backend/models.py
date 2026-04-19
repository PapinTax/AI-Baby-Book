from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from database import Base
import datetime


class Child(Base):
    __tablename__ = "children"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    birth_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    milestones = relationship("Milestone", back_populates="child")


class Photo(Base):
    __tablename__ = "photos"

    id = Column(Integer, primary_key=True)
    file_path = Column(String(1000), unique=True, nullable=False)
    filename = Column(String(255), nullable=False)
    taken_at = Column(DateTime, nullable=True)   # from EXIF
    file_size = Column(Integer, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    thumbnail_path = Column(String(1000), nullable=True)
    processed = Column(Boolean, default=False)
    scan_session_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    milestones = relationship("Milestone", back_populates="photo")


class Milestone(Base):
    __tablename__ = "milestones"

    id = Column(Integer, primary_key=True)
    photo_id = Column(Integer, ForeignKey("photos.id"), nullable=False)
    child_id = Column(Integer, ForeignKey("children.id"), nullable=True)
    milestone_type = Column(String(100), nullable=False)   # e.g. "first_steps"
    label = Column(String(200), nullable=False)             # human-readable
    description = Column(Text, nullable=True)               # Claude's narrative
    confidence = Column(Float, nullable=False)              # 0.0 - 1.0
    approximate_age = Column(String(50), nullable=True)     # e.g. "~9 months"
    approved = Column(Boolean, nullable=True)               # None=pending, True=yes, False=no
    evidence = Column(JSON, nullable=True)                  # raw Claude reasoning
    detected_at = Column(DateTime, default=datetime.datetime.utcnow)

    photo = relationship("Photo", back_populates="milestones")
    child = relationship("Child", back_populates="milestones")


MILESTONE_TYPES = [
    "first_smile",
    "first_laugh",
    "tummy_time",
    "first_roll",
    "sitting_up",
    "first_crawl",
    "first_pull_to_stand",
    "first_stand",
    "first_steps",
    "first_walk",
    "first_solid_food",
    "first_birthday",
    "birthday",
    "first_bath",
    "first_tooth",
    "first_words",
    "vacation",
    "holiday",
    "memorable_moment",
]
