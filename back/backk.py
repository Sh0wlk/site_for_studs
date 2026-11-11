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


# ==============================================================================
# 1. КОНФИГУРАЦИЯ И ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ
# ==============================================================================

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


# ==============================================================================
# 2. МОДЕЛИ ДАННЫХ (PYDANTIC SCHEMAS)
# ==============================================================================

class RegisterSchema(BaseModel):
    full_name: str
    email: str
    password: str


class LoginSchema(BaseModel):
    email: str
    password: str


class RoleUpdateSchema(BaseModel):
    user_id: int
    role: str
    group_id: Optional[int] = None


class NewsCreateSchema(BaseModel):
    title: str
    content: str
    tag: str = "Общее"


class QuestionSchema(BaseModel):
    text: str
    options: List[str]
    correct_index: int


class TestCreateSchema(BaseModel):
    title: str
    group_id: int
    questions: List[QuestionSchema]


class TestSubmitSchema(BaseModel):
    answers: List[int]


class TicketCreateSchema(BaseModel):
    recipient_type: str
    recipient_id: Optional[int] = None
    subject: str
    question: str


class TicketAnswerSchema(BaseModel):
    answer: str


# ==============================================================================
# 3. БАЗА ДАННЫХ И НАЧАЛЬНОЕ НАПОЛНЕНИЕ
# ==============================================================================

async def create_tables(cur) -> None:
    """Создание всех необходимых таблиц в PostgreSQL."""
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
            api_token TEXT
        );
    """)

    await cur.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tag VARCHAR(50) DEFAULT 'Общее',
            author_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    await cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            id SERIAL PRIMARY KEY,
            group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
            day_of_week VARCHAR(20) NOT NULL,
            time_slot VARCHAR(30) NOT NULL,
            subject TEXT NOT NULL,
            room VARCHAR(30) NOT NULL,
            teacher_name TEXT NOT NULL,
            lesson_type VARCHAR(30) DEFAULT 'Лекция'
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)


async def seed_demo_data(cur) -> None:
    """Заполнение базовых групп, новостей и расписания при первом запуске."""
    for grp in ["ИВТ-101", "ЭК-202", "ПИ-301"]:
        await cur.execute(
            "INSERT INTO groups (name) VALUES (%s) ON CONFLICT DO NOTHING",
            (grp,)
        )

    await cur.execute("SELECT COUNT(*) as cnt FROM news")
    if (await cur.fetchone())["cnt"] == 0:
        await cur.execute("""
            INSERT INTO news (title, content, tag, author_name) VALUES
            (
                'Старт университетского хакатона 2026',
                'Приглашаем команды всех факультетов принять участие в разработке цифровых сервисов для нашего вуза.',
                'Мероприятия',
                'Деканат'
            ),
            (
                'Изменения в графике работы библиотеки',
                'С понедельника читальный зал работает до 21:00 по студенческому билету.',
                'Общее',
                'Администрация'
            )
        """)

    await cur.execute("SELECT COUNT(*) as cnt FROM schedule")
    if (await cur.fetchone())["cnt"] == 0:
        await cur.execute("SELECT id FROM groups WHERE name = 'ИВТ-101'")
        group_row = await cur.fetchone()
        if group_row:
            gid = group_row["id"]
            await cur.execute("""
                INSERT INTO schedule (group_id, day_of_week, time_slot, subject, room, teacher_name, lesson_type) VALUES
                (%s, 'Понедельник', '09:00 - 10:30', 'Алгоритмы и структуры данных', 'Ауд. 304', 'Смирнов А.В.', 'Лекция'),
                (%s, 'Понедельник', '10:45 - 12:15', 'Базы данных (PostgreSQL)', 'Комп. класс 12', 'Козлова Е.Н.', 'Практика'),
                (%s, 'Вторник', '09:00 - 10:30', 'Веб-разработка и API', 'Комп. класс 05', 'Смирнов А.В.', 'Лабораторная'),
                (%s, 'Среда', '12:45 - 14:15', 'Информационная безопасность', 'Ауд. 410', 'Волков Д.С.', 'Лекция')
            """, (gid, gid, gid, gid))


async def init_db() -> None:
    """Главная функция инициализации базы данных."""
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


# ==============================================================================
# 4. ЗАВИСИМОСТИ И БЕЗОПАСНОСТЬ
# ==============================================================================

async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Получение текущего пользователя по Bearer-токену из заголовка."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Не передан токен авторизации")

    token = authorization.replace("Bearer ", "").strip()
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT u.id, u.full_name, u.email, u.role, u.group_id, g.name as group_name
                FROM users u
                LEFT JOIN groups g ON u.group_id = g.id
                WHERE u.api_token = %s
            """, (token,))
            user = await cur.fetchone()

    if not user:
        raise HTTPException(status_code=401, detail="Неверный или устаревший токен")
    return user


def require_roles(user: dict, allowed_roles: List[str], error_msg: str = "Недостаточно прав") -> None:
    """Проверка соответствия роли пользователя разрешенному списку."""
    if user["role"] not in allowed_roles:
        raise HTTPException(status_code=403, detail=error_msg)


# ==============================================================================
# 5. ЭНДПОИНТЫ АВТОРИЗАЦИИ И ПРОФИЛЯ
# ==============================================================================

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
            await conn.commit()
    except psycopg.Error as exc:
        raise HTTPException(status_code=500, detail=f"Ошибка базы данных: {exc}")

    return {"status": "success", "token": token, "user_id": new_user["id"]}

@app.post("/api/login")
async def login(data: LoginSchema):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT u.id, u.full_name, u.email, u.password_hash, u.role, u.group_id, u.api_token, g.name as group_name
                FROM users u
                LEFT JOIN groups g ON u.group_id = g.id
                WHERE u.email = %s
            """, (data.email,))
            user = await cur.fetchone()

    if not user or not bcrypt.checkpw(data.password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        raise HTTPException(status_code=401, detail="Неверный Email или пароль")

    del user["password_hash"]
    return {"status": "success", "user": user}


@app.get("/api/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


# ==============================================================================
# 6. УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ, РОЛЯМИ И ПРЕПОДАВАТЕЛЯМИ
# ==============================================================================

@app.get("/api/users")
async def list_users(current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["deanery", "admin"])

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT u.id, u.full_name, u.email, u.role, u.group_id, g.name as group_name
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
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE users SET role = %s, group_id = %s WHERE id = %s",
                (data.role, data.group_id, data.user_id)
            )
        await conn.commit()

    return {"status": "success"}


@app.get("/api/teachers")
async def list_teachers(current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT id, full_name, email FROM users WHERE role = 'teacher' ORDER BY full_name")
            teachers = await cur.fetchall()

            await cur.execute("SELECT * FROM groups ORDER BY name")
            groups = await cur.fetchall()

    return {"teachers": teachers, "groups": groups}


# ==============================================================================
# 7. НОВОСТИ И РАСПИСАНИЕ ЗАНЯТИЙ
# ==============================================================================

@app.get("/api/news")
async def get_news(current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT id, title, content, tag, author_name,
                       to_char(created_at, 'DD.MM.YYYY HH24:MI') as date
                FROM news
                ORDER BY id DESC
            """)
            return await cur.fetchall()


@app.post("/api/news")
async def create_news(data: NewsCreateSchema, current_user: dict = Depends(get_current_user)):
    require_roles(current_user, ["deanery", "admin"], "Публиковать новости может только Деканат или Админ")

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO news (title, content, tag, author_name) VALUES (%s, %s, %s, %s)",
                (data.title, data.content, data.tag, current_user["full_name"])
            )
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

            await cur.execute("SELECT * FROM schedule WHERE group_id = %s ORDER BY id", (target_group,))
            lessons = await cur.fetchall()

    return {
        "groups": groups,
        "selected_group": target_group,
        "lessons": lessons
    }


# ==============================================================================
# 8. МОДУЛЬ ТЕСТИРОВАНИЯ
# ==============================================================================

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
            score = 0
            for idx, q in enumerate(questions):
                if idx < len(data.answers) and data.answers[idx] == q["correct_index"]:
                    score += 1

            max_score = len(questions)
            await cur.execute(
                "DELETE FROM test_results WHERE test_id = %s AND student_id = %s",
                (test_id, current_user["id"])
            )
            await cur.execute(
                "INSERT INTO test_results (test_id, student_id, score, max_score) VALUES (%s, %s, %s, %s)",
                (test_id, current_user["id"], score, max_score)
            )
        await conn.commit()

    return {"score": score, "max_score": max_score}


# ==============================================================================
# 9. ОБРАЩЕНИЯ И ОБРАТНАЯ СВЯЗЬ (ВОПРОС-ОТВЕТ)
# ==============================================================================

@app.get("/api/tickets")
async def get_tickets(current_user: dict = Depends(get_current_user)):
    base_query = """
        SELECT tk.id, tk.subject, tk.question, tk.answer, tk.status, tk.recipient_type,
               to_char(tk.created_at, 'DD.MM HH24:MI') as date,
               s.full_name as student_name, g.name as group_name,
               r.full_name as recipient_name
        FROM tickets tk
        JOIN users s ON tk.student_id = s.id
        LEFT JOIN groups g ON s.group_id = g.id
        LEFT JOIN users r ON tk.recipient_id = r.id
    """

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            if current_user["role"] == "student":
                await cur.execute(base_query + " WHERE tk.student_id = %s ORDER BY tk.id DESC", (current_user["id"],))
            elif current_user["role"] == "teacher":
                await cur.execute(base_query + " WHERE tk.recipient_id = %s ORDER BY tk.id DESC", (current_user["id"],))
            else:
                await cur.execute(base_query + " ORDER BY tk.id DESC")
            return await cur.fetchall()

@app.post("/api/tickets")
async def create_ticket(data: TicketCreateSchema, current_user: dict = Depends(get_current_user)):
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO tickets (student_id, recipient_type, recipient_id, subject, question)
                VALUES (%s, %s, %s, %s, %s)
            """, (current_user["id"], data.recipient_type, data.recipient_id, data.subject, data.question))
        await conn.commit()

    return {"status": "success"}


@app.post("/api/tickets/{ticket_id}/answer")
async def answer_ticket(ticket_id: int, data: TicketAnswerSchema, current_user: dict = Depends(get_current_user)):
    if current_user["role"] == "student":
        raise HTTPException(status_code=403, detail="Студент не может закрывать обращения")

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE tickets SET answer = %s, status = 'answered' WHERE id = %s",
                (data.answer, ticket_id)
            )
        await conn.commit()

    return {"status": "success"}


# ==============================================================================
# 10. ТОЧКА ВХОДА ДЛЯ ЗАПУСКА СЕРВЕРА
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backk:app", host="127.0.0.1", port=8000, reload=True)