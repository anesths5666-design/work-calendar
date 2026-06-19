from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlmodel import Session, select, SQLModel
from database import create_db_and_tables, get_session, engine
from models import User, Absence
from auth import hash_password, verify_password, create_token, decode_token

class RegisterRequest(SQLModel):
    username: str
    full_name: str
    password: str

def create_default_admin():
    with Session(engine) as session:
        existing = session.exec(select(User).where(User.username == "admin")).first()
        if existing:
            return
        admin = User(
            username="admin",
            full_name="Διαχειριστής",
            hashed_password=hash_password("admin123"),
            role="admin",
        )
        session.add(admin)
        session.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    create_default_admin()
    yield

app = FastAPI(title="Ημερολόγιο Δουλειάς", lifespan=lifespan)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def get_current_user(token: str = Depends(oauth2_scheme),
                     session: Session = Depends(get_session)) -> User:
    username = decode_token(token)
    if username is None:
        raise HTTPException(status_code=401, detail="Άκυρο ή ληγμένο token")
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Ο χρήστης δεν υπάρχει")
    return user

def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Μόνο ο διαχειριστής έχει πρόσβαση")
    return current_user

@app.post("/admin/create-employee")
def create_employee(req: RegisterRequest,
                    admin: User = Depends(get_current_admin),
                    session: Session = Depends(get_session)):
    existing = session.exec(select(User).where(User.username == req.username)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Το username υπάρχει ήδη")
    if len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Ο κωδικός πρέπει να έχει 4+ χαρακτήρες")
    user = User(
        username=req.username,
        full_name=req.full_name,
        hashed_password=hash_password(req.password),
        role="employee",
    )
    session.add(user)
    session.commit()
    return {"message": f"Ο υπάλληλος {req.full_name} δημιουργήθηκε"}


@app.get("/admin/employees")
def list_employees(admin: User = Depends(get_current_admin),
                   session: Session = Depends(get_session)):
    employees = session.exec(select(User).where(User.role == "employee")).all()
    return [{"id": e.id, "username": e.username, "full_name": e.full_name} for e in employees]

@app.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(),
          session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == form.username)).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Λάθος username ή κωδικός")
    token = create_token(user.username)
    return {"access_token": token, "token_type": "bearer", "role": user.role}

@app.get("/me")
def read_me(current_user: User = Depends(get_current_user)):
    return {"username": current_user.username,
            "full_name": current_user.full_name,
            "role": current_user.role}
