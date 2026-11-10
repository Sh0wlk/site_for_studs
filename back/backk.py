# -*- coding: utf-8 -*-
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
import psycopg
import secrets
import hashlib
import bcrypt

app = FastAPI(title="Base Auth API")

# Настройка CORS для связи с фронтендом
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене замените на конкретный URL фронтенда
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Строка подключения к вашей локальной базе данных
DB_CONFIG = "dbname=my_local_db user=postgres password=Sakuromoti3! host=127.0.0.1 port=5432"

# Инициализация асинхронного пула соединений с вашей конфигурацией
pool = AsyncConnectionPool(conninfo=DB_CONFIG, open=False)

async def BD_startup():
    try:
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username VARCHAR(50) UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        api_token TEXT
                    );
                """)
                await conn.commit()
    except psycopg.Error as e:
        print(f"Ошибка при создании таблицы: {e}")

@app.on_event("startup")
async def open_pool():
    await pool.open()
    await BD_startup()

@app.on_event("shutdown")
async def close_pool():
    await pool.close()

# Модель данных для регистрации/входа
class UserSchema(BaseModel):
    username: str
    password: str

# Эндпоинт для регистрации
@app.post("/api/register")
async def register_user(user: UserSchema):
    # Хеширование пароля с помощью bcrypt
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(user.password.encode('utf-8'), salt).decode('utf-8')
    
    # Генерация случайного API-ключа
    api_token = secrets.token_hex(32)

    try:
        # Получаем асинхронное соединение из пула
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Проверка, существует ли пользователь
                await cur.execute("SELECT id FROM users WHERE username = %s", (user.username,))
                if await cur.fetchone():
                    raise HTTPException(status_code=400, detail="Пользователь уже существует")
                
                # Вставка нового пользователя
                await cur.execute(
                    "INSERT INTO users (username, password_hash, api_token) VALUES (%s, %s, %s) RETURNING id",
                    (user.username, hashed_password, api_token)
                )
                await conn.commit()
                return {"status": "success", "message": "Пользователь успешно зарегистрирован"}
    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail=f"Ошибка базы данных: {str(e)}")

# Эндпоинт для входа (добавьте в конец backend/main.py)
@app.post("/api/login")
async def login_user(user: UserSchema):
    try:
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT id, username, password_hash, api_token FROM users WHERE username = %s",
                    (user.username,)
                )
                db_user = await cur.fetchone()

                if not db_user:
                    raise HTTPException(status_code=401, detail="Неверный логин или пароль")

                # Проверка пароля через bcrypt
                is_valid = bcrypt.checkpw(
                    user.password.encode('utf-8'),
                    db_user["password_hash"].encode('utf-8')
                )
                if not is_valid:
                    raise HTTPException(status_code=401, detail="Неверный логин или пароль")

                return {
                    "status": "success",
                    "token": db_user["api_token"],
                    "username": db_user["username"]
                }
    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail=f"Ошибка базы данных: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
