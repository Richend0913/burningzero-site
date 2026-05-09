"""BURNING ZERO — FastAPI signal relay server."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

import db
import auth
from relay import relay

logger = logging.getLogger("server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

STATIC_DIR = Path(__file__).parent


# ── Relay background task ──

async def relay_loop():
    """Check signal.json every 2 seconds."""
    while True:
        try:
            relay.check_and_execute()
        except Exception as e:
            logger.error(f"Relay error: {e}")
        await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    task = asyncio.create_task(relay_loop())
    logger.info("BURNING ZERO server started — relay loop active")
    yield
    task.cancel()


app = FastAPI(title="BURNING ZERO", lifespan=lifespan)


# ── Auth dependency ──

async def get_current_user(request: Request) -> dict:
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = auth.decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_admin(request: Request) -> dict:
    user = await get_current_user(request)
    if not auth.is_admin(user["email"]):
        raise HTTPException(status_code=403, detail="Admin only")
    return user


# ── Request models ──

class RegisterReq(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=6, max_length=200)
    mt5_login: int
    mt5_server: str = Field(min_length=1, max_length=200)
    mt5_password: str = Field(min_length=1, max_length=200)


class LoginReq(BaseModel):
    email: str
    password: str


class SettingsReq(BaseModel):
    conf_threshold: float | None = None
    lot_mode: str | None = None
    lot_size: float | None = None
    risk_pct: float | None = None
    strategies_a: bool | None = None
    strategies_b: bool | None = None
    strategies_d: bool | None = None
    active: bool | None = None


# ── API Routes ──

@app.post("/api/register")
async def register(req: RegisterReq):
    if db.get_user_by_email(req.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if db.count_approved_users() >= 10:
        raise HTTPException(status_code=400, detail="All 10 slots are taken")

    hashed = auth.hash_password(req.password)
    uid = db.create_user(
        name=req.name, email=req.email, password_hash=hashed,
        mt5_login=req.mt5_login, mt5_server=req.mt5_server,
        mt5_password=req.mt5_password,
    )

    # Auto-approve admin
    if auth.is_admin(req.email):
        db.approve_user(uid)

    token = auth.create_token(uid, req.email)
    return {"token": token, "user_id": uid, "status": "pending"}


@app.post("/api/login")
async def login(req: LoginReq):
    user = db.get_user_by_email(req.email)
    if not user or not auth.verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = auth.create_token(user["id"], user["email"])
    return {
        "token": token,
        "user_id": user["id"],
        "status": user["status"],
        "is_admin": auth.is_admin(user["email"]),
    }


@app.get("/api/me")
async def get_me(user: dict = Depends(get_current_user)):
    safe = {k: v for k, v in user.items() if k not in ("password_hash", "mt5_password")}
    safe["is_admin"] = auth.is_admin(user["email"])
    return safe


@app.put("/api/settings")
async def update_settings(req: SettingsReq, user: dict = Depends(get_current_user)):
    updates = {}
    if req.conf_threshold is not None:
        updates["conf_threshold"] = max(0.64, min(0.74, req.conf_threshold))
    if req.lot_mode is not None and req.lot_mode in ("fixed", "dynamic"):
        updates["lot_mode"] = req.lot_mode
    if req.lot_size is not None:
        updates["lot_size"] = max(0.01, min(10.0, req.lot_size))
    if req.risk_pct is not None:
        updates["risk_pct"] = max(1.0, min(10.0, req.risk_pct))
    if req.strategies_a is not None:
        updates["strategies_a"] = int(req.strategies_a)
    if req.strategies_b is not None:
        updates["strategies_b"] = int(req.strategies_b)
    if req.strategies_d is not None:
        updates["strategies_d"] = int(req.strategies_d)
    if req.active is not None:
        if req.active and user["status"] != "approved":
            raise HTTPException(status_code=400, detail="Account not approved yet")
        updates["active"] = int(req.active)

    db.update_user_settings(user["id"], **updates)
    return {"ok": True}


@app.get("/api/trades")
async def get_trades(user: dict = Depends(get_current_user)):
    trades = db.get_trades(user["id"])
    return {"trades": trades}


@app.get("/api/status")
async def get_status(user: dict = Depends(get_current_user)):
    positions = db.get_positions(user["id"])
    trades = db.get_trades(user["id"], limit=50)
    total_pnl = sum(t["profit"] for t in trades)
    wins = sum(1 for t in trades if t["profit"] > 0)
    total = len(trades)
    return {
        "positions": positions,
        "trades": trades,
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
        "total_trades": total,
        "active": bool(user["active"]),
        "status": user["status"],
    }


@app.get("/api/slots")
async def get_slots():
    approved = db.count_approved_users()
    return {"total": 10, "used": approved, "remaining": max(0, 10 - approved)}


# ── Admin routes ──

@app.get("/api/users")
async def list_users(admin: dict = Depends(require_admin)):
    users = db.get_all_users()
    safe = []
    for u in users:
        s = {k: v for k, v in u.items() if k not in ("password_hash", "mt5_password")}
        s["positions"] = len(db.get_positions(u["id"]))
        trades = db.get_trades(u["id"])
        s["total_trades"] = len(trades)
        s["total_pnl"] = round(sum(t["profit"] for t in trades), 2)
        safe.append(s)
    return {"users": safe}


@app.post("/api/approve/{user_id}")
async def approve(user_id: int, admin: dict = Depends(require_admin)):
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if db.count_approved_users() >= 10:
        raise HTTPException(status_code=400, detail="All 10 slots are taken")
    db.approve_user(user_id)
    return {"ok": True}


@app.post("/api/reject/{user_id}")
async def reject(user_id: int, admin: dict = Depends(require_admin)):
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.reject_user(user_id)
    return {"ok": True}


@app.get("/api/admin/status")
async def admin_status(admin: dict = Depends(require_admin)):
    users = db.get_all_users()
    positions = db.get_all_positions()
    trades = db.get_all_trades(limit=200)
    return {
        "total_users": len(users),
        "approved": sum(1 for u in users if u["status"] == "approved"),
        "pending": sum(1 for u in users if u["status"] == "pending"),
        "active_bots": sum(1 for u in users if u["active"]),
        "open_positions": len(positions),
        "total_trades": len(trades),
        "total_pnl": round(sum(t["profit"] for t in trades), 2),
    }


# ── Page serving ──

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login", response_class=HTMLResponse)
async def serve_login():
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/register", response_class=HTMLResponse)
async def serve_register():
    return FileResponse(STATIC_DIR / "register.html")


@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/admin", response_class=HTMLResponse)
async def serve_admin():
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/app", response_class=HTMLResponse)
async def serve_app():
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/backtest.html", response_class=HTMLResponse)
async def serve_backtest():
    return FileResponse(STATIC_DIR / "backtest.html")


# Serve static files (js, json, etc.)
@app.get("/{filename:path}")
async def serve_static(filename: str):
    filepath = STATIC_DIR / filename
    if filepath.is_file():
        return FileResponse(filepath)
    raise HTTPException(status_code=404, detail="Not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
