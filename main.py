from typing import Annotated
from contextlib import asynccontextmanager
import re

from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlmodel import SQLModel, Field, Session, create_engine, select
from sqlalchemy.exc import IntegrityError, NoResultFound, ProgrammingError

try:
    from seed import users, records
except ModuleNotFoundError as exc:
    if exc.name != "seed":
        raise
    # Seed data is optional; the app can still run and accept registrations.
    users = []
    records = []


class User(SQLModel, table=True):
    login: str = Field(primary_key=True)
    password: str
    fio: str
    phone: str | None = Field(default=None)
    email: str | None = Field(default=None)
    role: str | None = Field(default="user")


class Record(SQLModel, table=True):
    id: int | None = Field(primary_key=True, default=None)
    course: str
    payment: str
    date: str
    user_login: str
    status: str | None = Field(default="Новая")


class Feedback(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    record_id: int = Field(foreign_key="record.id")
    user_login: str
    text: str


class Login(SQLModel):
    login: str
    password: str


class NewRecord(SQLModel):
    course: str
    payment: str
    date: str


class RegistrationForm(SQLModel):
    login: str
    password: str
    fio: str
    phone: str
    email: str


class NewStatus(SQLModel):
    record_id: int
    new_status: str


class NewFeedback(SQLModel):
    record_id: int
    new_feedback: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_engine("sqlite:///db.sqlite3")
    SQLModel.metadata.create_all(bind=engine)

    # Add the registration columns to databases created before they existed.
    with engine.begin() as connection:
        existing_columns = {
            column._mapping["name"]
            for column in connection.exec_driver_sql("PRAGMA table_info(user)")
        }
        for column_name in ("phone", "email"):
            if column_name not in existing_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE user ADD COLUMN {column_name} VARCHAR"
                )

    with Session(bind=engine) as session:
        try:
            session.add_all([User(**user) for user in users])
            session.commit()
        except (IntegrityError, ProgrammingError):
            session.rollback()

    with Session(bind=engine) as session:
        try:
            existing_records = session.scalars(select(Record)).unique().all()
            if len(existing_records) == 0:
                session.add_all([Record(**record) for record in records])
                session.commit()
        except (IntegrityError, ProgrammingError):
            session.rollback()

    yield


engine = create_engine("sqlite:///db.sqlite3")

app = FastAPI(lifespan=lifespan)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="./static"))


@app.get("/login")
def get_login(request: Request):
    return templates.TemplateResponse(request, "login.jinja2")


@app.post("/login")
def post_login(request: Request, login: Annotated[Login, Form()]):
    with Session(bind=engine) as session:
        try:
            expr = (
                select(User)
                .where(User.login == login.login)
                .where(User.password == login.password)
            )
            user = session.exec(expr).one()
        except NoResultFound:
            return templates.TemplateResponse(
                request, "login.jinja2", context={"error": "Неверные данные"}
            )

    response = RedirectResponse(
        "/admin" if user.role == "moderator" else "/profile", status_code=302
    )

    response.set_cookie("login", user.login)
    response.set_cookie("role", user.role)

    return response


@app.get("/register")
def get_register(request: Request):
    return templates.TemplateResponse(request, "register.jinja2")


@app.post("/register")
def post_register(request: Request, form: Annotated[RegistrationForm, Form()]):
    form.login = form.login.strip()
    form.fio = " ".join(form.fio.split())
    form.phone = form.phone.strip()
    form.email = form.email.strip()

    validation_errors = (
        (re.fullmatch(r"[A-Za-z0-9]{6,}", form.login), "Логин: латиница и цифры, не менее 6 символов"),
        (re.fullmatch(r"\S{8,}", form.password), "Пароль должен содержать не менее 8 символов без пробелов"),
        (re.fullmatch(r"[А-Яа-яЁё ]+", form.fio), "ФИО должно содержать только кириллицу и пробелы"),
        (re.fullmatch(r"8\([0-9]{3}\)[0-9]{3}-[0-9]{2}-[0-9]{2}", form.phone), "Телефон укажите в формате 8(999)123-45-67"),
        (re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", form.email), "Введите корректный адрес электронной почты"),
    )
    for is_valid, message in validation_errors:
        if not is_valid:
            return templates.TemplateResponse(
                request, "register.jinja2", context={"error": message}
            )

    user = User(
        login=form.login,
        password=form.password,
        fio=form.fio,
        phone=form.phone,
        email=form.email,
        role="user",
    )
    with Session(bind=engine) as session:
        try:
            session.add(user)
            session.commit()
        except IntegrityError:
            session.rollback()
            return templates.TemplateResponse(
                request,
                "register.jinja2",
                context={"error": "Пользователь уже существует"},
            )

    return RedirectResponse("/login", status_code=302)


@app.get("/profile")
def get_profile(request: Request):
    if request.cookies.get("role") != "user":
        return RedirectResponse("/login", status_code=302)

    with Session(bind=engine) as session:
        expr = select(Record).where(Record.user_login == request.cookies.get("login"))
        records = session.exec(expr).all()
        feedbacks = session.exec(select(Feedback)).all()

    return templates.TemplateResponse(
        request,
        "profile.jinja2",
        context={
            "login": request.cookies.get("login"),
            "records": records,
            "feedbacks": feedbacks,
        },
    )


@app.get("/profile/new")
def get_new_record(request: Request):
    if request.cookies.get("role") != "user":
        return RedirectResponse("/login", status_code=302)

    return templates.TemplateResponse(
        request,
        "record.jinja2",
        context={
            "login": request.cookies.get("login"),
        },
    )


@app.post("/profile/new")
def post_new_record(request: Request, form: Annotated[NewRecord, Form()]):
    if request.cookies.get("role") != "user":
        return RedirectResponse("/login", status_code=302)

    with Session(bind=engine) as session:
        try:
            session.add(
                Record(
                    course=form.course,
                    payment=form.payment,
                    date=form.date,
                    user_login=request.cookies.get("login"),
                )
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            return templates.TemplateResponse(
                request,
                "record.jinja2",
                context={
                    "error": "Не удалось создать заявку",
                    "login": request.cookies.get("login"),
                },
            )

    return RedirectResponse("/profile", status_code=302)


@app.post("/profile/feedback")
def post_feedback(request: Request, feedback: Annotated[NewFeedback, Form()]):
    if request.cookies.get("role") != "user":
        return RedirectResponse("/login", status_code=302)

    with Session(bind=engine) as session:
        try:
            record = session.exec(
                select(Record).where(Record.id == feedback.record_id)
            ).one()
            if record.user_login != request.cookies.get("login"):
                return RedirectResponse("/profile", status_code=302)
            if record.status != "Обучение завершено":
                return RedirectResponse("/profile", status_code=302)
            session.add(
                Feedback(
                    record_id=record.id,
                    user_login=request.cookies.get("login"),
                    text=feedback.new_feedback.strip(),
                )
            )
            session.commit()
            return RedirectResponse("/profile", status_code=302)
        except NoResultFound:
            return RedirectResponse("/profile", status_code=302)


@app.post("/status")
def post_status(request: Request, new_status: Annotated[NewStatus, Form()]):
    with Session(bind=engine) as session:
        try:
            record = session.exec(
                select(Record).where(Record.id == new_status.record_id)
            ).one()
            record.status = new_status.new_status
            session.commit()
            session.refresh(record)
            return RedirectResponse("/admin", status_code=302)
        except NoResultFound:
            return RedirectResponse("/admin", status_code=302)


@app.get("/admin")
def get_admin(request: Request):
    if request.cookies.get("role") != "moderator":
        return RedirectResponse("/login", status_code=302)

    with Session(bind=engine) as session:
        expr = select(Record)
        records = session.exec(expr).all()

    return templates.TemplateResponse(
        request,
        "admin.jinja2",
        context={"login": request.cookies.get("login"), "records": records},
    )


@app.get("/logout")
def get_logout():
    response = RedirectResponse("/login", status_code=302)

    response.delete_cookie("login")
    response.delete_cookie("role")

    return response
