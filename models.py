from datetime import datetime, date
from sqlmodel import SQLModel, Field

class User(SQLModel, table=True):
    id: int | None=  Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    full_name: str
    hashed_password: str
    role: str = "employee"

class Absence(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    absence_date:date
    reason: str = ""
    status: str = "pending"
    seen_by_admin: bool = False
    created_at: datetime = Field(default_factory=datetime.now)

class Shift(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    shift_date: date
    start_time: str 
    end_time: str
