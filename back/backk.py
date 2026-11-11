# -*- coding: utf-8 -*-
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
import psycopg
import secrets
import bcrypt

app = FastAPI(title="University Portal MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_CONFIG = "dbname=my_local_db user=postgres password=Sakuromoti3! host=127.0.0.1 port=5432"
pool = AsyncConnectionPool(conninfo=DB_CONFIG, open=False)

async def init_db():
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
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
            for grp in ["ИВТ-101", "ЭК-202", "ПИ-301"]:
                await cur.execute("INSERT INTO groups (name) VALUES (%s) ON CONFLICT DO NOTHING", (grp,))
        await conn.commit()

@app.on_event("startup")
async def startup():
    await pool.open()
    await init_db()

@app.on_event("shutdown")
async def shutdown():
    await pool.close()

# --- Схемы данных ---
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

# --- Проверка текущего пользователя по токену ---
async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Не передан токен авторизации")
    token = authorization.replace("Bearer ", "")
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
                raise HTTPException(status_code=401, detail="Неверный токен")
            return user

# --- Эндпоинты авторизации ---
@app.post("/api/register")
async def register(data: RegisterSchema):
    salt = bcrypt.gensalt()
    pw_hash = bcrypt.hashpw(data.password.encode('utf-8'), salt).decode('utf-8')
    token = secrets.token_hex(32)
    try:
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT id FROM users WHERE email = %s", (data.email,))
                if await cur.fetchone():
                    raise HTTPException(status_code=400, detail="Этот Email уже зарегистрирован")
                await cur.execute(
                    "INSERT INTO users (full_name, email, password_hash, role, api_token) VALUES (%s, %s, %s, 'guest', %s) RETURNING id",
                    (data.full_name, data.email, pw_hash, token)
                )
                new_user = await cur.fetchone()
            await conn.commit()
            return {"status": "success", "token": token, "user_id": new_user["id"]}
    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/login")
async def login(data: LoginSchema):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT u.id, u.full_name, u.email, u.password_hash, u.role, u.group_id, u.api_token, g.name as group_name
                FROM users u LEFT JOIN groups g ON u.group_id = g.id
                WHERE u.email = %s
            """, (data.email,))
            user = await cur.fetchone()
            if not user or not bcrypt.checkpw(data.password.encode('utf-8'), user["password_hash"].encode('utf-8')):
                raise HTTPException(status_code=401, detail="Неверный Email или пароль")
            
            del user["password_hash"]
            return {"status": "success", "user": user}

@app.get("/api/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user

# --- Управление пользователями (Деканат и Админ) ---
@app.get("/api/users")
async def list_users(current_user: dict = Depends(get_current_user)):
    if current_user["role"] not in ["deanery", "admin"]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT u.id, u.full_name, u.email, u.role, u.group_id, g.name as group_name
                FROM users u LEFT JOIN groups g ON u.group_id = g.id
                ORDER BY u.id DESC
            """)
            users = await cur.fetchall()
            await cur.execute("SELECT * FROM groups ORDER BY name")
            groups = await cur.fetchall()
            return {"users": users, "groups": groups}

@app.post("/api/users/role")
async def assign_role(data: RoleUpdateSchema, current_user: dict = Depends(get_current_user)):
    if current_user["role"] not in ["deanery", "admin"]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    # Деканат не может выдавать роль деканата или админа
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backk:app", host="127.0.0.1", port=8000, reload=True)
