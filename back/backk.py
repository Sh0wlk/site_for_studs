# -*- coding: utf-8 -*-
import json
import secrets
from typing import List, Optional

import bcrypt
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel
import random
import smtplib
from email.message import EmailMessage

# 1. config and init

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_USER = "sasasilivanov5@gmail.com"
SMTP_PASS = "iauufmwhkfdqdzsm"     # your_gmai_password

PENDING_2FA_CODES = {}

def send_2fa_email(to_email: str, code: str, full_name: str) -> None:
    print(f"\n[2FA КОД ДЛЯ {to_email}]: {code}\n")
    if "твоя_почта" in SMTP_USER:
        return
    msg = EmailMessage()
    msg["Subject"] = f"Код подтверждения входа: {code}"
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg.set_content(f"Здравствуйте, {full_name}!\nВаш 4-значный код для входа в Портал ВУЗа: {code}")
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


DB_CONFIG = "dbname=my_local_db user=postgres password=Sakuromoti3! host=127.0.0.1 port=5432"

app = FastAPI(
    title="University Portal MVP",
    description="API для единого образовательного портала университета",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pool = AsyncConnectionPool(conninfo=DB_CONFIG, open=False)

# 2. pydantic

class Verify2FASchema(BaseModel):
    email: str
    code: str

class RegisterSchema(BaseModel):
    full_name: str
    email: str
    password: str

class LoginSchema(BaseModel):
    email: str
    password: str

class AvatarUpdateSchema(BaseModel):
    avatar_url: str

class RoleUpdateSchema(BaseModel):
    user_id: int
    role: str
    group_id: Optional[int] = None

class NewsCreateSchema(BaseModel):
    title: str
    content: str
    tag: str = "Общее"
    image_url: Optional[str] = None

class ScheduleSchema(BaseModel):
    group_id: int
    day_of_week: str
    time_start: str
    time_end: str
    subject: str
    room: str
    corp: str
    teacher_name: str
    lesson_type: str
    lesson_date: Optional[str] = None

class TicketMessageSchema(BaseModel):
    text: str
    
class AttendanceMarkSchema(BaseModel):
    lesson_id: int
    student_id: int
    status: str
    grade: Optional[str] = ""

class BookCreateSchema(BaseModel):
    title: str
    author: str
    subject: str
    file_name: str
    file_data: str


class LessonToggleSchema(BaseModel):
    cancel: bool = False
    new_type: Optional[str] = None

class ScheduleCopySchema(BaseModel):
    source_group_id: int
    target_group_id: int
    source_day: str
    target_day: Optional[str] = None

class ExamCreateSchema(BaseModel):
    group_id: int
    course: int
    academic_year: str
    subject: str
    exam_date: str
    room: str
    doc_name: Optional[str] = None
    doc_data: Optional[str] = None

class DeadlineCreateSchema(BaseModel):
    group_id: int
    subject: str
    title: str
    due_date: str  # YYYY-MM-DD

class FlashcardItemSchema(BaseModel):
    front: str
    back: str

class DeckCreateSchema(BaseModel):
    title: str
    tags: str
    cards: List[FlashcardItemSchema]

class QuestionSchema(BaseModel):
    text: str
    options: List[str]
    correct_index: int

class TestCreateSchema(BaseModel):
    title: str
    group_id: int
    questions: List[QuestionSchema]

class PresetCreateSchema(BaseModel):
    name: str
    group_id: int
    day_filter: str = "ALL"

class PresetApplySchema(BaseModel):
    preset_id: int
    target_group_id: int
    target_day: Optional[str] = None

class TestSubmitSchema(BaseModel):
    answers: List[int]

class TicketCreateSchema(BaseModel):
    recipient_type: str
    recipient_id: Optional[int] = None
    subject: str
    question: str

class TicketAnswerSchema(BaseModel):
    answer: str

# 3. db (you can translate it from code to pgAdmin if preferable)

async def create_tables(cur) -> None:
    await cur.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id SERIAL PRIMARY KEY,
            name VARCHAR(50) UNIQUE NOT NULL
        );
    """)

    await cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            full_name TEXT NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role VARCHAR(20) DEFAULT 'guest',
            group_id INTEGER REFERENCES groups(id) ON DELETE SET NULL,
            api_token TEXT,
            avatar_url TEXT
        );
    """)

    await cur.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tag VARCHAR(50) DEFAULT 'Общее',
            author_name TEXT,
            image_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    await cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            id SERIAL PRIMARY KEY,
            group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
            day_of_week VARCHAR(20) NOT NULL,
            time_start TIMESTAMP NOT NULL,
            time_end TIMESTAMP NOT NULL,
            subject TEXT NOT NULL,
            room VARCHAR(20) NOT NULL,
            corp VARCHAR(10) NOT NULL,
            teacher_name TEXT NOT NULL,
            lesson_type VARCHAR(30) DEFAULT 'Лекция',
            is_changed BOOLEAN DEFAULT FALSE,
            lesson_date DATE
        );
    """)

    await cur.execute("""
        CREATE TABLE IF NOT EXISTS exam_sessions (
            id SERIAL PRIMARY KEY,
            group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
            course INTEGER NOT NULL,
            academic_year VARCHAR(20) NOT NULL,
            subject TEXT NOT NULL,
            exam_date DATE NOT NULL,
            room VARCHAR(50) NOT NULL,
            teacher_name TEXT NOT NULL,
            doc_name TEXT,
            doc_data TEXT
        );
    """)

    await cur.execute("""
        CREATE TABLE IF NOT EXISTS flashcard_decks (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            tags TEXT NOT NULL,
            author_name TEXT NOT NULL,
            author_role VARCHAR(20) NOT NULL,
            cards JSONB NOT NULL
        );
    """)

    await cur.execute("""
        CREATE TABLE IF NOT EXISTS tests (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
            teacher_name TEXT NOT NULL,
            questions JSONB NOT NULL
        );
    """)

    await cur.execute("""
        CREATE TABLE IF NOT EXISTS test_results (
            id SERIAL PRIMARY KEY,
            test_id INTEGER REFERENCES tests(id) ON DELETE CASCADE,
            student_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            score INTEGER NOT NULL,
            max_score INTEGER NOT NULL,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    await cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id SERIAL PRIMARY KEY,
            student_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            recipient_type VARCHAR(20) NOT NULL,
            recipient_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            subject TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT,
            status VARCHAR(20) DEFAULT 'new',
            created_by_staff BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    await cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id SERIAL PRIMARY KEY,
            actor_name TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    await cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id SERIAL PRIMARY KEY,
            lesson_id INTEGER REFERENCES schedule(id) ON DELETE CASCADE,
            student_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            status VARCHAR(20) NOT NULL DEFAULT 'present',
            updated_by TEXT,
            UNIQUE(lesson_id, student_id)
        );
    """)

    await cur.execute("""
        CREATE TABLE IF NOT EXISTS ticket_messages (
            id SERIAL PRIMARY KEY,
            ticket_id INTEGER REFERENCES tickets(id) ON DELETE CASCADE,
            sender_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            sender_name TEXT NOT NULL,
            sender_role VARCHAR(20) NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    await cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule_presets (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            lessons JSONB NOT NULL,
            created_by TEXT NOT NULL
        );
    """)

    await cur.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS grade VARCHAR(10) DEFAULT '';")

    await cur.execute("""
        CREATE TABLE IF NOT EXISTS library_books (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            subject TEXT NOT NULL,
            uploaded_by TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_data TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    await cur.execute("""
        CREATE TABLE IF NOT EXISTS deadlines (
            id SERIAL PRIMARY KEY,
            group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
            subject TEXT NOT NULL,
            title TEXT NOT NULL,
            due_date DATE NOT NULL,
            author_name TEXT NOT NULL
        );
    """)

async def write_audit(cur, actor_name: str, action: str, details: str) -> None:
    """Запись события в журнал безопасности."""
    await cur.execute(
        "INSERT INTO audit_logs (actor_name, action, details) VALUES (%s, %s, %s)",
        (actor_name, action, details)
    )

async def seed_demo_data(cur) -> None:
    """Заполнение стартовых групп, админа, новостей, расписания и карточек."""
    for grp in ["ИВТ-101", "ЭК-202", "ПИ-301"]:
        await cur.execute("INSERT INTO groups (name) VALUES (%s) ON CONFLICT DO NOTHING", (grp,))

    await cur.execute("SELECT id FROM users WHERE email = 'admin@uni.ru'")
    if not await cur.fetchone():
        pw_hash = bcrypt.hashpw("admin123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        await cur.execute(
            "INSERT INTO users (full_name, email, password_hash, role, api_token) VALUES (%s, %s, %s, 'admin', %s)",
            ("Главный Администратор", "admin@uni.ru", pw_hash, secrets.token_hex(32))
        )

    await cur.execute("SELECT COUNT(*) as cnt FROM flashcard_decks")
    if (await cur.fetchone())["cnt"] == 0:
        cards = json.dumps([
            {"front": "Что такое PRIMARY KEY?", "back": "Уникальный ключ строки таблицы в SQL."},
            {"front": "Сложность бинарного поиска?", "back": "O(log n)"}
        ], ensure_ascii=False)
        await cur.execute(
            "INSERT INTO flashcard_decks (title, tags, author_name, author_role, cards) VALUES (%s, %s, %s, 'teacher', %s::jsonb)",
            ("База к сессии: Алгоритмы и SQL", "сессия ивт 2026 1 курс sql", "Смирнов А.В.", cards)
        )

async def init_db() -> None:
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await create_tables(cur)
            await seed_demo_data(cur)
        await conn.commit()

@app.on_event("startup")
async def on_startup() -> None:
    await pool.open()
    await init_db()

@app.on_event("shutdown")
async def on_shutdown() -> None:
    await pool.close()

# 4. security +

async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Не передан токен авторизации")

    token = authorization.replace("Bearer ", "").strip()
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT u.id, u.full_name, u.email, u.role, u.group_id, u.avatar_url, g.name as group_name
                FROM users u
                LEFT JOIN groups g ON u.group_id = g.id
                WHERE u.api_token = %s
            """, (token,))
            user = await cur.fetchone()

    if not user:
        raise HTTPException(status_code=401, detail="Неверный или устаревший токен")
    return user


def require_roles(user: dict, allowed_roles: List[str], error_msg: str = "Недостаточно прав") -> None:
    if user["role"] not in allowed_roles:
        raise HTTPException(status_code=403, detail=error_msg)

# 5. logIn - endPoints

@app.post("/api/register")
async def register(data: RegisterSchema):
    salt = bcrypt.gensalt()
    pw_hash = bcrypt.hashpw(data.password.encode("utf-8"), salt).decode("utf-8")
    token = secrets.token_hex(32)

    try:
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT id FROM users WHERE email = %s", (data.email,))
                if await cur.fetchone():
                    raise HTTPException(status_code=400, detail="Этот Email уже зарегистрирован")

                await cur.execute("""
                    INSERT INTO users (full_name, email, password_hash, role, api_token)
                    VALUES (%s, %s, %s, 'guest', %s)
                    RETURNING id
                """, (data.full_name, data.email, pw_hash, token))
                new_user = await cur.fetchone()
                await write_audit(cur, data.full_name, "Регистрация", f"Создана заявка #{new_user['id']} ({data.email})")
            await conn.commit()
    except psycopg.Error as exc:
        raise HTTPException(status_code=500, detail=f"Ошибка базы данных: {exc}")

    return {"status": "success", "token": token, "user_id": new_user["id"]}

@app.post("/api/login")
async def login(data: LoginSchema):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT u.id, u.full_name, u.email, u.password_hash, u.role, u.group_id, u.avatar_url, u.api_token, g.name as group_name
                FROM users u
                LEFT JOIN groups g ON u.group_id = g.id
                WHERE u.email = %s
            """, (data.email,))
            user = await cur.fetchone()

    if not user or not bcrypt.checkpw(data.password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        raise HTTPException(status_code=401, detail="Неверный Email или пароль")

    del user["password_hash"]

    # Для ролей с повышенными правами отправляем 4-значный код на Email
    if user["role"] in ["teacher", "deanery", "admin"]:
        code = f"{random.randint(1000, 9999)}"
        PENDING_2FA_CODES[user["email"]] = {"code": code, "user": user}
        try:
            send_2fa_email(user["email"], code, user["full_name"])
        except Exception as e:
            print(f"Ошибка отправки Email: {e}")
        return {"status": "2fa_required", "email": user["email"]}

    return {"status": "success", "user": user}


@app.post("/api/verify-2fa")
async def verify_2fa(data: Verify2FASchema):
    entry = PENDING_2FA_CODES.get(data.email)
    if not entry or entry["code"] != data.code.strip():
        raise HTTPException(status_code=401, detail="Неверный 4-значный код")
    del PENDING_2FA_CODES[data.email]
    return {"status": "success", "user": entry["user"]}


@app.get("/api/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user

# 6. role priorities

@app.get("/api/users")
async def list_users(current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["deanery", "admin"])
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT u.id, u.full_name, u.email, u.role, u.group_id, u.avatar_url, g.name as group_name
                FROM users u
                LEFT JOIN groups g ON u.group_id = g.id
                ORDER BY u.id DESC
            """)
            users = await cur.fetchall()
            await cur.execute("SELECT * FROM groups ORDER BY name")
            groups = await cur.fetchall()
    return {"users": users, "groups": groups}

@app.post("/api/users/role")
async def assign_role(data: RoleUpdateSchema, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["deanery", "admin"])
    if data.user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Нельзя изменить роль самому себе")
    if current_user["role"] == "deanery" and data.role in ["deanery", "admin"]:
        raise HTTPException(status_code=403, detail="Деканат может назначать только Учеников и Учителей")

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT full_name FROM users WHERE id = %s", (data.user_id,))
            target = await cur.fetchone()
            await cur.execute(
                "UPDATE users SET role = %s, group_id = %s WHERE id = %s",
                (data.role, data.group_id, data.user_id)
            )
            target_name = target["full_name"] if target else f"ID {data.user_id}"
            await write_audit(cur, current_user["full_name"], "Смена роли", f"{target_name} -> роль '{data.role}'")
        await conn.commit()
    return {"status": "success"}


@app.get("/api/teachers")
async def list_teachers(current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT id, full_name, email, avatar_url FROM users WHERE role = 'teacher' ORDER BY full_name")
            teachers = await cur.fetchall()
            await cur.execute("SELECT * FROM groups ORDER BY name")
            groups = await cur.fetchall()
    return {"teachers": teachers, "groups": groups}


@app.post("/api/users/avatar")
async def update_avatar(data: AvatarUpdateSchema, current_user: dict = Depends(get_current_user)):
    if len(data.avatar_url) > 500_000:
        raise HTTPException(status_code=400, detail="Файл изображения слишком большой")
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE users SET avatar_url = %s WHERE id = %s", (data.avatar_url, current_user["id"]))
        await conn.commit()
    return {"status": "success", "avatar_url": data.avatar_url}

# 7. news + timemanaging

@app.get("/api/news")
async def get_news(current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT id, title, content, tag, author_name, image_url,
                       to_char(created_at, 'DD.MM.YYYY HH24:MI') as date
                FROM news ORDER BY id DESC
            """)
            return await cur.fetchall()


@app.post("/api/news")
async def create_news(data: NewsCreateSchema, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["deanery", "admin"], "Публиковать новости может только Деканат или Админ")
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO news (title, content, tag, author_name, image_url) VALUES (%s, %s, %s, %s, %s)",
                (data.title, data.content, data.tag, current_user["full_name"], data.image_url)
            )
            await write_audit(cur, current_user["full_name"], "Публикация новости", data.title)
        await conn.commit()
    return {"status": "success"}


@app.get("/api/schedule")
async def get_schedule(group_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    target_group = group_id or current_user.get("group_id")
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM groups ORDER BY name")
            groups = await cur.fetchall()
            if not target_group and groups:
                target_group = groups[0]["id"]
            await cur.execute("""
                SELECT id, group_id, day_of_week,
                       to_char(time_start, 'HH24:MI') as start_fmt,
                       to_char(time_end, 'HH24:MI') as end_fmt,
                       time_start::text as time_start_raw,
                       time_end::text as time_end_raw,
                       subject, room, corp, teacher_name, lesson_type,
                       COALESCE(is_changed, FALSE) as is_changed,
                       lesson_date::text as lesson_date
                FROM schedule
                WHERE group_id = %s
                ORDER BY time_start ASC
            """, (target_group,))
            lessons = await cur.fetchall()
    return {"groups": groups, "selected_group": target_group, "lessons": lessons}


@app.post("/api/schedule")
async def add_schedule_lesson(data: ScheduleSchema, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["deanery", "admin"], "Изменять расписание может только Деканат или Админ")
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO schedule (group_id, day_of_week, time_start, time_end, subject, room, corp, teacher_name, lesson_type, is_changed, lesson_date)
                VALUES (%s, %s, %s::timestamp, %s::timestamp, %s, %s, %s, %s, %s, TRUE, %s::date)
            """, (
                data.group_id, data.day_of_week, data.time_start, data.time_end,
                data.subject, str(data.room), str(data.corp), data.teacher_name,
                data.lesson_type, data.lesson_date
            ))
            await write_audit(cur, current_user["full_name"], "Добавление пары", f"{data.subject} ({data.day_of_week})")
        await conn.commit()
    return {"status": "success"}


@app.post("/api/schedule/{lesson_id}/toggle-change")
async def toggle_lesson_change(lesson_id: int, data: LessonToggleSchema, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["deanery", "admin"])
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT subject, lesson_type, is_changed FROM schedule WHERE id = %s", (lesson_id,))
            lesson = await cur.fetchone()
            if not lesson:
                raise HTTPException(status_code=404, detail="Пара не найдена")

            if data.cancel:
                new_type = "Отменена"
                new_changed = True
            else:
                new_type = data.new_type or lesson["lesson_type"]
                new_changed = not lesson["is_changed"]

            await cur.execute(
                "UPDATE schedule SET is_changed = %s, lesson_type = %s WHERE id = %s",
                (new_changed, new_type, lesson_id)
            )
            await write_audit(cur, current_user["full_name"], "Изменение расписания", f"{lesson['subject']} -> {new_type}")
        await conn.commit()
    return {"status": "success"}


@app.post("/api/schedule/copy")
async def copy_schedule(data: ScheduleCopySchema, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["deanery", "admin"])
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            if data.source_day == "ALL":
                await cur.execute("SELECT * FROM schedule WHERE group_id = %s", (data.source_group_id,))
                rows = await cur.fetchall()
                for r in rows:
                    await cur.execute("""
                        INSERT INTO schedule (group_id, day_of_week, time_start, time_end, subject, room, corp, teacher_name, lesson_type, is_changed, lesson_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                    """, (
                        data.target_group_id, r["day_of_week"], r["time_start"], r["time_end"],
                        r["subject"], r["room"], r["corp"], r["teacher_name"], r["lesson_type"], r["lesson_date"]
                    ))
                copied_count = len(rows)
            else:
                await cur.execute(
                    "SELECT * FROM schedule WHERE group_id = %s AND day_of_week = %s",
                    (data.source_group_id, data.source_day)
                )
                rows = await cur.fetchall()
                target_d = data.target_day or data.source_day
                for r in rows:
                    await cur.execute("""
                        INSERT INTO schedule (group_id, day_of_week, time_start, time_end, subject, room, corp, teacher_name, lesson_type, is_changed, lesson_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                    """, (
                        data.target_group_id, target_d, r["time_start"], r["time_end"],
                                                r["subject"], r["room"], r["corp"], r["teacher_name"], r["lesson_type"], r["lesson_date"]
                    ))
                copied_count = len(rows)

            await write_audit(cur, current_user["full_name"], "Копирование расписания", f"Скопировано пар: {copied_count}")
        await conn.commit()
    return {"status": "success", "copied": copied_count}

@app.delete("/api/schedule/{lesson_id}")
async def delete_schedule_lesson(lesson_id: int, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["deanery", "admin"])
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT subject FROM schedule WHERE id = %s", (lesson_id,))
            row = await cur.fetchone()
            await cur.execute("DELETE FROM schedule WHERE id = %s", (lesson_id,))
            if row:
                await write_audit(cur, current_user["full_name"], "Удаление пары", row["subject"])
        await conn.commit()
    return {"status": "success"}


@app.get("/api/schedule/presets")
async def get_schedule_presets(current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["deanery", "admin"])
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT id, name, jsonb_array_length(lessons) as count, created_by FROM schedule_presets ORDER BY id DESC")
            return await cur.fetchall()


@app.post("/api/schedule/presets")
async def save_schedule_preset(data: PresetCreateSchema, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["deanery", "admin"])
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            if data.day_filter == "ALL":
                await cur.execute("""
                    SELECT day_of_week, to_char(time_start, 'HH24:MI') as start_t, to_char(time_end, 'HH24:MI') as end_t,
                           subject, room, corp, teacher_name, lesson_type
                    FROM schedule WHERE group_id = %s ORDER BY time_start ASC
                """, (data.group_id,))
            else:
                await cur.execute("""
                    SELECT day_of_week, to_char(time_start, 'HH24:MI') as start_t, to_char(time_end, 'HH24:MI') as end_t,
                           subject, room, corp, teacher_name, lesson_type
                    FROM schedule WHERE group_id = %s AND day_of_week = %s ORDER BY time_start ASC
                """, (data.group_id, data.day_filter))
            rows = await cur.fetchall()
            if not rows:
                raise HTTPException(status_code=400, detail="Нет пар для сохранения в пресет")

            await cur.execute(
                "INSERT INTO schedule_presets (name, lessons, created_by) VALUES (%s, %s::jsonb, %s)",
                (data.name, json.dumps(rows, ensure_ascii=False), current_user["full_name"])
            )
            await write_audit(cur, current_user["full_name"], "Пресет расписания", f"Сохранён пресет '{data.name}' ({len(rows)} пар)")
        await conn.commit()
    return {"status": "success"}


@app.post("/api/schedule/presets/apply")
async def apply_schedule_preset(data: PresetApplySchema, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["deanery", "admin"])
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT name, lessons FROM schedule_presets WHERE id = %s", (data.preset_id,))
            preset = await cur.fetchone()
            if not preset:
                raise HTTPException(status_code=404, detail="Пресет не найден")

            lessons = preset["lessons"]
            for l in lessons:
                day_val = data.target_day if data.target_day else l["day_of_week"]
                await cur.execute("""
                    INSERT INTO schedule (group_id, day_of_week, time_start, time_end, subject, room, corp, teacher_name, lesson_type, is_changed)
                    VALUES (%s, %s, %s::timestamp, %s::timestamp, %s, %s, %s, %s, %s, TRUE)
                """, (
                    data.target_group_id, day_val, f"2026-11-09 {l['start_t']}:00", f"2026-11-09 {l['end_t']}:00",
                    l["subject"], l["room"], l["corp"], l["teacher_name"], l["lesson_type"]
                ))
            await write_audit(cur, current_user["full_name"], "Применение пресета", f"Пресет '{preset['name']}' -> группа #{data.target_group_id}")
        await conn.commit()
    return {"status": "success", "applied": len(lessons)}

@app.get("/api/exams")
async def get_exams(group_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    target_group = group_id or current_user.get("group_id")
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            if target_group:
                await cur.execute("""
                    SELECT id, group_id, course, academic_year, subject,
                           exam_date::text as exam_date, room, teacher_name, doc_name,
                           (doc_data IS NOT NULL AND doc_data != '') as has_doc
                    FROM exam_sessions WHERE group_id = %s ORDER BY exam_date ASC
                """, (target_group,))
            else:
                await cur.execute("""
                    SELECT id, group_id, course, academic_year, subject,
                           exam_date::text as exam_date, room, teacher_name, doc_name,
                           (doc_data IS NOT NULL AND doc_data != '') as has_doc
                    FROM exam_sessions ORDER BY exam_date ASC
                """)
            return await cur.fetchall()

@app.get("/api/exams/{exam_id}/doc")
async def download_exam_doc(exam_id: int, current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT doc_name, doc_data FROM exam_sessions WHERE id = %s", (exam_id,))
            row = await cur.fetchone()
    if not row or not row["doc_data"]:
        raise HTTPException(status_code=404, detail="Документ не прикреплен")
    return row

@app.post("/api/exams")
async def create_exam(data: ExamCreateSchema, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["teacher", "deanery", "admin"], "Добавлять экзамены могут только преподаватели и деканат")
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO exam_sessions (group_id, course, academic_year, subject, exam_date, room, teacher_name, doc_name, doc_data)
                VALUES (%s, %s, %s, %s, %s::date, %s, %s, %s, %s)
            """, (
                data.group_id, data.course, data.academic_year, data.subject,
                data.exam_date, data.room, current_user["full_name"], data.doc_name, data.doc_data
            ))
            await write_audit(cur, current_user["full_name"], "Добавлен экзамен", f"{data.subject} ({data.academic_year})")
        await conn.commit()
    return {"status": "success"}

# 8. cards and testing

@app.get("/api/decks")
async def get_decks(current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM flashcard_decks ORDER BY id DESC")
            return await cur.fetchall()


@app.post("/api/decks")
async def create_deck(data: DeckCreateSchema, current_user: dict = Depends(get_current_user)):
    if current_user["role"] == "guest":
        raise HTTPException(status_code=403, detail="Подтвердите аккаунт для создания карточек")
    cards_json = json.dumps([c.dict() for c in data.cards], ensure_ascii=False)
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO flashcard_decks (title, tags, author_name, author_role, cards)
                VALUES (%s, %s, %s, %s, %s::jsonb)
            """, (data.title, data.tags, current_user["full_name"], current_user["role"], cards_json))
        await conn.commit()
    return {"status": "success"}


@app.get("/api/tests")
async def get_tests(current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            if current_user["role"] == "student":
                await cur.execute("""
                    SELECT t.id, t.title, t.teacher_name, g.name as group_name, t.questions,
                           r.score, r.max_score
                    FROM tests t
                    JOIN groups g ON t.group_id = g.id
                    LEFT JOIN test_results r ON r.test_id = t.id AND r.student_id = %s
                    WHERE t.group_id = %s
                    ORDER BY t.id DESC
                """, (current_user["id"], current_user["group_id"]))
            else:
                await cur.execute("""
                    SELECT t.id, t.title, t.teacher_name, g.name as group_name, t.questions,
                           (SELECT COUNT(*) FROM test_results r WHERE r.test_id = t.id) as submissions
                    FROM tests t
                    JOIN groups g ON t.group_id = g.id
                    ORDER BY t.id DESC
                """)
            return await cur.fetchall()


@app.get("/api/tests/{test_id}/results")
async def get_test_results(test_id: int, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["teacher", "deanery", "admin"])
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT title FROM tests WHERE id = %s", (test_id,))
            test = await cur.fetchone()
            await cur.execute("""
                SELECT u.full_name, g.name as group_name, r.score, r.max_score,
                       to_char(r.submitted_at, 'DD.MM.YYYY HH24:MI') as date
                FROM test_results r
                JOIN users u ON r.student_id = u.id
                LEFT JOIN groups g ON u.group_id = g.id
                WHERE r.test_id = %s
                ORDER BY u.full_name ASC
            """, (test_id,))
            rows = await cur.fetchall()
    return {"title": test["title"] if test else "Тест", "results": rows}
@app.post("/api/tests")
async def create_test(data: TestCreateSchema, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["teacher", "admin"], "Создавать тесты может только Учитель")
    questions_json = json.dumps([q.dict() for q in data.questions], ensure_ascii=False)
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO tests (title, group_id, teacher_name, questions) VALUES (%s, %s, %s, %s::jsonb)",
                (data.title, data.group_id, current_user["full_name"], questions_json)
            )
        await conn.commit()
    return {"status": "success"}


@app.post("/api/tests/{test_id}/submit")
async def submit_test(test_id: int, data: TestSubmitSchema, current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT questions FROM tests WHERE id = %s", (test_id,))
            test = await cur.fetchone()
            if not test:
                raise HTTPException(status_code=404, detail="Тест не найден")

            questions = test["questions"]
            score = sum(
                1 for idx, q in enumerate(questions)
                if idx < len(data.answers) and data.answers[idx] == q["correct_index"]
            )
            max_score = len(questions)
            await cur.execute("DELETE FROM test_results WHERE test_id = %s AND student_id = %s", (test_id, current_user["id"]))
            await cur.execute(
                "INSERT INTO test_results (test_id, student_id, score, max_score) VALUES (%s, %s, %s, %s)",
                (test_id, current_user["id"], score, max_score)
            )
        await conn.commit()
    return {"score": score, "max_score": max_score}

# 9. tickets and logs
@app.get("/api/tickets")
async def get_tickets(current_user: dict = Depends(get_current_user)):
    base_query = """
        SELECT tk.id, tk.student_id, tk.recipient_id, tk.subject, tk.question, tk.status, tk.recipient_type,
               to_char(tk.created_at, 'DD.MM HH24:MI') as date,
               s.full_name as student_name, s.avatar_url as student_avatar, s.role as sender_role, g.name as group_name,
               r.full_name as recipient_name, r.avatar_url as recipient_avatar
        FROM tickets tk
        JOIN users s ON tk.student_id = s.id
        LEFT JOIN groups g ON s.group_id = g.id
        LEFT JOIN users r ON tk.recipient_id = r.id
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            if current_user["role"] == "student":
                await cur.execute(base_query + " WHERE tk.student_id = %s OR tk.recipient_id = %s ORDER BY tk.id DESC", (current_user["id"], current_user["id"]))
            elif current_user["role"] == "teacher":
                await cur.execute(base_query + " WHERE tk.recipient_id = %s OR tk.student_id = %s ORDER BY tk.id DESC", (current_user["id"], current_user["id"]))
            else:
                await cur.execute(base_query + " ORDER BY tk.id DESC")
            tickets = await cur.fetchall()

            for tk in tickets:
                await cur.execute("""
                    SELECT id, sender_id, sender_name, sender_role, text,
                           to_char(created_at, 'DD.MM HH24:MI') as date
                    FROM ticket_messages WHERE ticket_id = %s ORDER BY id ASC
                """, (tk["id"],))
                tk["messages"] = await cur.fetchall()
            return tickets


@app.post("/api/tickets")
async def create_ticket(data: TicketCreateSchema, current_user: dict = Depends(get_current_user)):
    is_staff = current_user["role"] in ["deanery", "admin"]
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                INSERT INTO tickets (student_id, recipient_type, recipient_id, subject, question, created_by_staff)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """, (current_user["id"], data.recipient_type, data.recipient_id, data.subject, data.question, is_staff))
            tid = (await cur.fetchone())["id"]
            await cur.execute("""
                INSERT INTO ticket_messages (ticket_id, sender_id, sender_name, sender_role, text)
                VALUES (%s, %s, %s, %s, %s)
            """, (tid, current_user["id"], current_user["full_name"], current_user["role"], data.question))
        await conn.commit()
    return {"status": "success"}


@app.post("/api/tickets/{ticket_id}/messages")
async def post_ticket_message(ticket_id: int, data: TicketMessageSchema, current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT student_id FROM tickets WHERE id = %s", (ticket_id,))
            tk = await cur.fetchone()
            if not tk:
                raise HTTPException(status_code=404, detail="Диалог не найден")

            await cur.execute("""
                INSERT INTO ticket_messages (ticket_id, sender_id, sender_name, sender_role, text)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, current_user["id"], current_user["full_name"], current_user["role"], data.text))

            # Если отвечает не автор обращения — помечаем как отвеченное
            new_status = "answered" if current_user["id"] != tk["student_id"] else "new"
            await cur.execute("UPDATE tickets SET status = %s WHERE id = %s", (new_status, ticket_id))
        await conn.commit()
    return {"status": "success"}


@app.get("/api/audit")
async def get_audit_logs(current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["admin", "deanery"])
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT id, actor_name, action, details,
                       to_char(created_at, 'DD.MM.YYYY HH24:MI:SS') as time
                FROM audit_logs ORDER BY id DESC LIMIT 50
            """)
            return await cur.fetchall()

@app.get("/api/notifications/summary")
async def get_notifications_summary(current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            guests_count = 0
            if current_user["role"] in ["deanery", "admin"]:
                await cur.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'guest'")
                guests_count = (await cur.fetchone())["cnt"]

            if current_user["role"] == "student":
                await cur.execute(
                    "SELECT COUNT(*) as cnt FROM tickets WHERE student_id = %s AND status = 'answered'",
                    (current_user["id"],)
                )
                tickets_count = (await cur.fetchone())["cnt"]
            elif current_user["role"] == "teacher":
                await cur.execute(
                    "SELECT COUNT(*) as cnt FROM tickets WHERE recipient_id = %s AND status = 'new'",
                    (current_user["id"],)
                )
                tickets_count = (await cur.fetchone())["cnt"]
            else:
                await cur.execute("SELECT COUNT(*) as cnt FROM tickets WHERE status = 'new'")
                tickets_count = (await cur.fetchone())["cnt"]

            await cur.execute("SELECT COUNT(*) as cnt FROM schedule WHERE is_changed = TRUE")
            changed_lessons = (await cur.fetchone())["cnt"]

    return {
        "guests_count": guests_count,
        "tickets_count": tickets_count,
        "changed_lessons": changed_lessons
    }

# ==============================================================================
# 10. ПОСЕЩАЕМОСТЬ, ОЦЕНКИ ЗА ПАРУ И БИБЛИОТЕКА
# ==============================================================================

@app.get("/api/schedule/{lesson_id}/attendance")
async def get_lesson_attendance(lesson_id: int, current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT id, group_id, subject, day_of_week, to_char(time_start, 'HH24:MI') as start_fmt FROM schedule WHERE id = %s", (lesson_id,))
            lesson = await cur.fetchone()
            if not lesson:
                raise HTTPException(status_code=404, detail="Пара не найдена")

            await cur.execute("""
                SELECT u.id, u.full_name, u.avatar_url,
                       COALESCE(a.status, 'present') as status,
                       COALESCE(a.grade, '') as grade
                FROM users u
                LEFT JOIN attendance a ON a.student_id = u.id AND a.lesson_id = %s
                WHERE u.group_id = %s AND u.role = 'student'
                ORDER BY u.full_name ASC
            """, (lesson_id, lesson["group_id"]))
            students = await cur.fetchall()
    return {"lesson": lesson, "students": students}


@app.post("/api/attendance")
async def mark_attendance(data: AttendanceMarkSchema, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["deanery", "teacher", "admin"], "Отмечать посещаемость и оценки могут только Деканат и Преподаватели")
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO attendance (lesson_id, student_id, status, grade, updated_by)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (lesson_id, student_id)
                DO UPDATE SET status = EXCLUDED.status, grade = EXCLUDED.grade, updated_by = EXCLUDED.updated_by
            """, (data.lesson_id, data.student_id, data.status, data.grade or "", current_user["full_name"]))
            await write_audit(cur, current_user["full_name"], "Журнал пары", f"Пара #{data.lesson_id}, студент #{data.student_id}: {data.status}, оценка '{data.grade or '—'}'")
        await conn.commit()
    return {"status": "success"}


@app.get("/api/my-absences")
async def get_my_absences(current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT s.subject,
                       COUNT(*) FILTER (WHERE a.status = 'absent') as unexcused,
                       COUNT(*) FILTER (WHERE a.status = 'excused') as excused,
                       STRING_AGG(NULLIF(a.grade, ''), ', ') as grades
                FROM attendance a
                JOIN schedule s ON a.lesson_id = s.id
                WHERE a.student_id = %s
                GROUP BY s.subject
                ORDER BY unexcused DESC
            """, (current_user["id"],))
            by_subject = await cur.fetchall()
    total_unexcused = sum(r["unexcused"] for r in by_subject)
    total_excused = sum(r["excused"] for r in by_subject)
    return {"total_unexcused": total_unexcused, "total_excused": total_excused, "by_subject": by_subject}


@app.get("/api/library")
async def get_library_books(current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT id, title, author, subject, uploaded_by, file_name,
                       to_char(created_at, 'DD.MM.YYYY') as date
                FROM library_books ORDER BY id DESC
            """)
            return await cur.fetchall()


@app.get("/api/library/{book_id}/download")
async def download_library_book(book_id: int, current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT file_name, file_data FROM library_books WHERE id = %s", (book_id,))
            row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Книга не найдена")
    return row


@app.post("/api/library")
async def upload_library_book(data: BookCreateSchema, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["teacher", "deanery", "admin"], "Загружать книги могут только преподаватели и деканат")
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO library_books (title, author, subject, uploaded_by, file_name, file_data)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (data.title, data.author, data.subject, current_user["full_name"], data.file_name, data.file_data))
            await write_audit(cur, current_user["full_name"], "Библиотека", f"Загружен учебник: {data.title}")
        await conn.commit()
    return {"status": "success"}

@app.get("/api/deadlines")
async def get_deadlines(current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            if current_user["role"] == "student" and current_user.get("group_id"):
                await cur.execute("""
                    SELECT d.id, d.subject, d.title, d.due_date::text as due_date, d.author_name, g.name as group_name
                    FROM deadlines d
                    JOIN groups g ON d.group_id = g.id
                    WHERE d.group_id = %s
                    ORDER BY d.due_date ASC
                """, (current_user["group_id"],))
            else:
                await cur.execute("""
                    SELECT d.id, d.subject, d.title, d.due_date::text as due_date, d.author_name, g.name as group_name
                    FROM deadlines d
                    JOIN groups g ON d.group_id = g.id
                    ORDER BY d.due_date ASC
                """)
            return await cur.fetchall()


@app.post("/api/deadlines")
async def create_deadline(data: DeadlineCreateSchema, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["teacher", "deanery", "admin"], "Добавлять дедлайны могут только преподаватели и деканат")
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO deadlines (group_id, subject, title, due_date, author_name)
                VALUES (%s, %s, %s, %s::date, %s)
            """, (data.group_id, data.subject, data.title, data.due_date, current_user["full_name"]))
            await write_audit(cur, current_user["full_name"], "Новый дедлайн", f"{data.subject}: {data.title} (до {data.due_date})")
        await conn.commit()
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backk:app", host="127.0.0.1", port=8000, reload=True)