from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.orm import sessionmaker, declarative_base

# Настройка базы данных SQLite
Base = declarative_base()
engine = create_engine('sqlite:///interviews.db', echo=True)
SessionLocal = sessionmaker(bind=engine)
session = SessionLocal()

class SurveyResponse(Base):
    __tablename__ = 'interviews2'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    username = Column(String)
    start_time = Column(String)
    end_time = Column(String)
    dialog = Column(Text)
    summary = Column(Text)

Base.metadata.create_all(engine)