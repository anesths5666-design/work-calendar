from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from datetime import date
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlmodel import Session, select, SQLModel
from database import create_db_and_tables, get_session, engine
from models import User, Absence
from auth import hash_password, verify_password, create_token, decode_token

# ---- Σχήματα αιτημάτων (όλα στην κορυφή) ----
class RegisterRequest(SQLModel):
    username: str
    full_name: str
    password: str

class AbsenceRequest(SQLModel):
    absence_date: date
    reason: str = ""

# ---- Φτιάχνει τον admin αυτόματα στην εκκίνηση ----
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

# Η "πύλη χρήστη": ελέγχει το token και βρίσκει τον χρήστη
def get_current_user(token: str = Depends(oauth2_scheme),
                     session: Session = Depends(get_session)) -> User:
    username = decode_token(token)
    if username is None:
        raise HTTPException(status_code=401, detail="Άκυρο ή ληγμένο token")
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Ο χρήστης δεν υπάρχει")
    return user

# Η "πύλη admin": χτίζει πάνω στην πύλη χρήστη
def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Μόνο ο διαχειριστής έχει πρόσβαση")
    return current_user

# ---- Admin: φτιάχνει υπαλλήλους ----
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

# ---- Admin: βλέπει όλους τους υπαλλήλους ----
@app.get("/admin/employees")
def list_employees(admin: User = Depends(get_current_admin),
                   session: Session = Depends(get_session)):
    employees = session.exec(select(User).where(User.role == "employee")).all()
    return [{"id": e.id, "username": e.username, "full_name": e.full_name} for e in employees]

# ---- Σύνδεση ----
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

# ---- Υπάλληλος: δηλώνει απουσία ----
@app.post("/absences")
def create_absence(req: AbsenceRequest,
                   current_user: User = Depends(get_current_user),
                   session: Session = Depends(get_session)):
    absence = Absence(
        user_id=current_user.id,
        absence_date=req.absence_date,
        reason=req.reason,
        seen_by_admin=False,
    )
    session.add(absence)
    session.commit()
    session.refresh(absence)
    return absence

# ---- Υπάλληλος: βλέπει τις δικές του απουσίες ----
@app.get("/absences")
def my_absences(current_user: User = Depends(get_current_user),
                session: Session = Depends(get_session)):
    return session.exec(
        select(Absence)
        .where(Absence.user_id == current_user.id)
        .order_by(Absence.absence_date)
    ).all()

# ---- Admin: βλέπει ΟΛΕΣ τις απουσίες (με το όνομα του υπαλλήλου) ----
@app.get("/admin/absences")
def all_absences(admin: User = Depends(get_current_admin),
                 session: Session = Depends(get_session)):
    absences = session.exec(select(Absence).order_by(Absence.absence_date)).all()
    result = []
    for a in absences:
        employee = session.get(User, a.user_id)   # βρες ΠΟΙΟΣ είναι ο υπάλληλος
        result.append({
            "id": a.id,
            "employee": employee.full_name if employee else "—",
            "absence_date": a.absence_date,
            "reason": a.reason,
            "status": a.status,
            "seen_by_admin": a.seen_by_admin,
        })
    return result

# ---- Admin: οι ΝΕΕΣ απουσίες (ειδοποιήσεις) ----
@app.get("/admin/notifications")
def notifications(admin: User = Depends(get_current_admin),
                  session: Session = Depends(get_session)):
    absences = session.exec(
        select(Absence)
        .where(Absence.seen_by_admin == False)     # μόνο τις μη ειδωμένες!
        .order_by(Absence.created_at.desc())
    ).all()
    result = []
    for a in absences:
        employee = session.get(User, a.user_id)
        result.append({
            "id": a.id,
            "employee": employee.full_name if employee else "—",
            "absence_date": a.absence_date,
            "reason": a.reason,
        })
    return result

# ---- Admin: εγκρίνει μια απουσία ----
@app.post("/admin/absences/{absence_id}/approve")
def approve_absence(absence_id: int,
                    admin: User = Depends(get_current_admin),
                    session: Session = Depends(get_session)):
    absence = session.get(Absence, absence_id)
    if not absence:
        raise HTTPException(status_code=404, detail="Η απουσία δεν βρέθηκε")
    absence.status = "approved"
    absence.seen_by_admin = True
    session.add(absence)
    session.commit()
    return {"message": "Η απουσία εγκρίθηκε"}

# ---- Admin: απορρίπτει μια απουσία ----
@app.post("/admin/absences/{absence_id}/reject")
def reject_absence(absence_id: int,
                   admin: User = Depends(get_current_admin),
                   session: Session = Depends(get_session)):
    absence = session.get(Absence, absence_id)
    if not absence:
        raise HTTPException(status_code=404, detail="Η απουσία δεν βρέθηκε")
    absence.status = "rejected"
    absence.seen_by_admin = True
    session.add(absence)
    session.commit()
    return {"message": "Η απουσία απορρίφθηκε"}

# ---- Admin: σύνοψη απουσιών ανά υπάλληλο ----
@app.get("/admin/stats")
def admin_stats(admin: User = Depends(get_current_admin),
                session: Session = Depends(get_session)):
    employees = session.exec(select(User).where(User.role == "employee")).all()
    result = []
    for e in employees:
        absences = session.exec(select(Absence).where(Absence.user_id == e.id)).all()
        approved = sum(1 for a in absences if a.status == "approved")
        pending = sum(1 for a in absences if a.status == "pending")
        result.append({
            "employee": e.full_name,
            "approved": approved,
            "pending": pending,
            "total": len(absences),
        })
    return result

# ---- Admin: διαγραφή υπαλλήλου (και των απουσιών του) ----
@app.delete("/admin/employees/{employee_id}")
def delete_employee(employee_id: int,
                    admin: User = Depends(get_current_admin),
                    session: Session = Depends(get_session)):
    employee = session.get(User, employee_id)
    if not employee or employee.role != "employee":
        raise HTTPException(status_code=404, detail="Ο υπάλληλος δεν βρέθηκε")
    # σβήσε πρώτα τις απουσίες του, μετά τον ίδιο
    absences = session.exec(select(Absence).where(Absence.user_id == employee_id)).all()
    for a in absences:
        session.delete(a)
    session.delete(employee)
    session.commit()
    return {"message": f"Ο υπάλληλος {employee.full_name} διαγράφηκε"}

app.mount("/", StaticFiles(directory="static", html=True), name="Static")
