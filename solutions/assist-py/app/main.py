from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
import socket

from fastapi import FastAPI, Depends, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
import httpx
import redis.asyncio as aioredis

from app.database import engine, get_db
from app.models import Base
from app import crud

OWNER = os.getenv("APP_OWNER", "anonymous")
SECRET_KEY = os.getenv("APP_SECRET", "default_secret")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))
HOSTNAME = socket.gethostname()

redis_client: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            # Serialize schema creation when several replicas start together.
            connection.execute(text("SELECT pg_advisory_xact_lock(468183)"))
        Base.metadata.create_all(bind=connection)
    redis_client = aioredis.from_url(
        REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
    )
    try:
        yield
    finally:
        await redis_client.aclose()
        redis_client = None


app = FastAPI(title="Personal Assist", lifespan=lifespan)


class NoteCreate(BaseModel):
    text: str


def _meta() -> dict:
    return {
        "hostname": HOSTNAME,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
async def root():
    return {
        "message": f"👋 Привет, {OWNER}!",
        "service": "personal-assistant",
        "version": "3.0",
        "endpoints": [
            "/me", "/notes", "/weather/{city}", "/secret/{key}",
            "/cache/stats",
        ],
        **_meta(),
    }


def _postgres_available() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


@app.get("/live")
async def live():
    return {"status": "alive"}


@app.get("/health")
async def health(response: Response):
    postgres_ok = await run_in_threadpool(_postgres_available)
    redis_ok = False
    if redis_client:
        try:
            redis_ok = bool(await redis_client.ping())
        except aioredis.RedisError:
            pass
    healthy = postgres_ok and redis_ok
    if not healthy:
        response.status_code = 503
    return {
        "status": "healthy" if healthy else "unavailable",
        "owner": OWNER,
        "postgres": postgres_ok,
        "redis": redis_ok,
        **_meta(),
    }


@app.get("/me")
async def me():
    return {
        "owner": OWNER,
        "secret_prefix": SECRET_KEY[:6]
        if SECRET_KEY != "default_secret"
        else "NOT_SET",
    }


@app.get("/secret/{key}")
async def secret(key: str):
    if key == SECRET_KEY:
        return {
            "flag": f"LAB2_SUCCESS_{OWNER.upper()}",
            "message": "The secret key is correct!",
        }
    return {
        "error": "The secret key is incorrect",
        "hint": "Check the APP_SECRET environment variable",
    }


WEATHER_CODES: dict[int, str] = {
    0: "☀️ Ясно", 1: "🌤 Малооблачно", 2: "⛅ Переменная облачность",
    3: "☁️ Пасмурно", 45: "🌫 Туман", 48: "🌫 Изморозь",
    51: "🌦 Лёгкая морось", 53: "🌦 Морось", 55: "🌧 Сильная морось",
    61: "🌧 Небольшой дождь", 63: "🌧 Дождь", 65: "🌧 Сильный дождь",
    71: "🌨 Небольшой снег", 73: "🌨 Снег", 75: "❄️ Сильный снег",
    80: "🌦 Ливень", 81: "🌧 Сильный ливень", 82: "⛈ Штормовой ливень",
    95: "⛈ Гроза", 96: "⛈ Гроза с градом", 99: "⛈ Сильная гроза с градом",
}


def _cache_key(city: str) -> str:
    return f"weather:{OWNER}:{city.strip().lower()}"


async def _get_cached(city: str) -> dict | None:
    if not redis_client:
        return None
    try:
        raw = await redis_client.get(_cache_key(city))
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def _set_cached(city: str, data: dict) -> None:
    if not redis_client:
        return
    try:
        await redis_client.setex(_cache_key(city), CACHE_TTL, json.dumps(data))
    except Exception:
        pass


@app.get("/weather/{city}")
async def weather(city: str):
    cached = await _get_cached(city)
    if cached:
        return {**cached, "source": "cache", **_meta()}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            geo_resp = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "ru"},
            )
            geo_data = geo_resp.json()

            if not geo_data.get("results"):
                return {"error": f"City «{city}» not found", **_meta()}

            location = geo_data["results"][0]
            lat = location["latitude"]
            lon = location["longitude"]
            city_name = location.get("name", city)
            country = location.get("country", "")

            weather_resp = await client.get(
                "https://weather.tk.gg/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                },
            )
            weather_data = weather_resp.json()["current"]

            code = weather_data.get("weather_code", -1)

            result = {
                "city": city_name,
                "country": country,
                "coordinates": {"lat": lat, "lon": lon},
                "temperature_c": weather_data["temperature_2m"],
                "humidity_pct": weather_data["relative_humidity_2m"],
                "wind_km_h": weather_data["wind_speed_10m"],
                "condition": WEATHER_CODES.get(code, f"Code {code}"),
                "owner": OWNER,
            }

            await _set_cached(city, result)
            return {**result, "source": "api", **_meta()}
    except Exception as e:
        return {"error": f"Failed to get weather: {type(e).__name__}: {e}", **_meta()}


@app.get("/cache/stats")
async def cache_stats():
    if not redis_client:
        return {"error": "Redis not available", **_meta()}
    try:
        pattern = f"weather:{OWNER}:*"
        keys = []
        async for key in redis_client.scan_iter(match=pattern):
            ttl = await redis_client.ttl(key)
            keys.append({"key": key, "ttl_seconds": ttl})
        return {
            "owner": OWNER,
            "cache_ttl_setting": CACHE_TTL,
            "cached_cities": len(keys),
            "keys": keys,
            **_meta(),
        }
    except Exception as e:
        return {"error": str(e), **_meta()}


@app.post("/notes")
async def create_note(note: NoteCreate, db: Session = Depends(get_db)):
    db_note = crud.create_note(db=db, text=note.text, owner=OWNER)
    return {
        "status": "saved",
        "note_id": db_note.id,
        "owner": db_note.owner,
        "text": db_note.text[:50],
    }


@app.get("/notes")
async def list_notes(db: Session = Depends(get_db)):
    db_notes = crud.get_notes(db=db, owner=OWNER)
    return {
        "owner": OWNER,
        "count": len(db_notes),
        "notes": [
            {
                "id": n.id,
                "text": n.text,
                "owner": n.owner,
                "created_at": n.created_at.isoformat(),
            }
            for n in db_notes
        ],
    }


@app.get("/notes/{note_id}")
async def get_note(note_id: int, db: Session = Depends(get_db)):
    note = crud.get_note_by_id(db=db, note_id=note_id)
    if not note:
        return {"error": f"Note {note_id} not found"}
    return {
        "id": note.id,
        "text": note.text,
        "owner": note.owner,
        "created_at": note.created_at.isoformat(),
    }


@app.delete("/notes/{note_id}")
async def delete_note(note_id: int, db: Session = Depends(get_db)):
    deleted = crud.delete_note(db=db, note_id=note_id)
    if not deleted:
        return {"error": f"Note {note_id} not found"}
    return {"status": "deleted", "note_id": note_id}
