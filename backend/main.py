import asyncio
import os
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, Float, Integer, String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Settings(BaseModel):
    api_title: str = "MediTriage AI API"
    api_version: str = "2.0.0"
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./meditriage.db")
    api_key: str = os.getenv("MEDITRIAGE_API_KEY", "")
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5500",
            "https://karthik321-coder.github.io",
        ]
    )


settings = Settings()
if os.getenv("ALLOWED_ORIGINS"):
    settings.allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]


class Base(DeclarativeBase):
    pass


class TriageEvent(Base):
    __tablename__ = "triage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(String(32), index=True)
    chief_complaint: Mapped[str] = mapped_column(String(500))
    esi_level: Mapped[int] = mapped_column(Integer, index=True)
    priority_score: Mapped[float] = mapped_column(Float)
    recommended_department: Mapped[str] = mapped_column(String(80))
    processing_ms: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class BedSnapshot(Base):
    __tablename__ = "bed_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    department: Mapped[str] = mapped_column(String(80), unique=True)
    total: Mapped[int] = mapped_column(Integer)
    occupied: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


app = FastAPI(
    title=settings.api_title,
    description="Real-time AI-powered emergency triage and hospital resource allocation system",
    version=settings.api_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)


class PatientIntake(BaseModel):
    age: int = Field(..., ge=0, le=120)
    gender: str = Field(..., pattern="^(male|female|other)$")
    chief_complaint: str = Field(..., min_length=4, max_length=500)
    heart_rate: int = Field(..., ge=20, le=300)
    systolic_bp: int = Field(..., ge=50, le=300)
    diastolic_bp: int = Field(..., ge=30, le=200)
    respiratory_rate: int = Field(..., ge=4, le=60)
    temperature: float = Field(..., ge=30.0, le=45.0)
    spo2: int = Field(..., ge=50, le=100)
    pain_scale: int = Field(..., ge=0, le=10)
    consciousness: str = Field(..., pattern="^(alert|verbal|pain|unresponsive)$")
    arrival_mode: str = Field(..., pattern="^(walk-in|ambulance|referred)$")
    symptoms: list[str] = Field(default_factory=list)
    medical_history: list[str] = Field(default_factory=list)


class TriageResult(BaseModel):
    patient_id: str
    esi_level: int
    esi_label: str
    priority_score: float
    recommended_wait: str
    recommended_department: str
    risk_flags: list[str]
    vital_alerts: list[str]
    timestamp: str


class BedUpdateRequest(BaseModel):
    occupied: int = Field(..., ge=0)


class BedProvisionItem(BaseModel):
    department: str = Field(..., min_length=2, max_length=80)
    total: int = Field(..., ge=1)
    occupied: int = Field(..., ge=0)


ESI_LABELS = {
    1: "Resuscitation - Immediate",
    2: "Emergent - 1-15 minutes",
    3: "Urgent - <=30 minutes",
    4: "Less Urgent - <=60 minutes",
    5: "Non-Urgent - <=120 minutes",
}
ESI_WAIT = {1: "Immediate", 2: "<=15 minutes", 3: "<=30 minutes", 4: "<=60 minutes", 5: "<=120 minutes"}
DEPT_MAP = {1: "Resuscitation Bay", 2: "Critical Care", 3: "Acute Care", 4: "Fast Track", 5: "Minor Care"}

request_windows: dict[str, deque[float]] = {}


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


def rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = request_windows.setdefault(client_ip, deque())
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    window.append(now)


def bootstrap_data() -> None:
    Base.metadata.create_all(engine)


def compute_vital_score(patient: PatientIntake) -> tuple[float, list[str]]:
    score = 0.0
    alerts: list[str] = []

    if patient.heart_rate < 50 or patient.heart_rate > 150:
        score += 26
        alerts.append(f"Critical HR: {patient.heart_rate} bpm")
    elif patient.heart_rate < 60 or patient.heart_rate > 120:
        score += 12
        alerts.append(f"Abnormal HR: {patient.heart_rate} bpm")

    if patient.systolic_bp < 90 or patient.systolic_bp > 180:
        score += 24
        alerts.append(f"Critical BP: {patient.systolic_bp}/{patient.diastolic_bp} mmHg")
    elif patient.systolic_bp < 100 or patient.systolic_bp > 160:
        score += 10
        alerts.append(f"Abnormal BP: {patient.systolic_bp}/{patient.diastolic_bp} mmHg")

    if patient.spo2 < 90:
        score += 28
        alerts.append(f"Critical SpO2: {patient.spo2}%")
    elif patient.spo2 < 95:
        score += 16
        alerts.append(f"Low SpO2: {patient.spo2}%")

    if patient.respiratory_rate < 8 or patient.respiratory_rate > 30:
        score += 24
        alerts.append(f"Critical RR: {patient.respiratory_rate}/min")
    elif patient.respiratory_rate < 12 or patient.respiratory_rate > 24:
        score += 10

    if patient.temperature > 40.0 or patient.temperature < 35.0:
        score += 18
        alerts.append(f"Critical Temp: {patient.temperature} C")
    elif patient.temperature > 38.5 or patient.temperature < 36.0:
        score += 8

    consciousness_score = {"alert": 0, "verbal": 12, "pain": 24, "unresponsive": 40}
    cs = consciousness_score.get(patient.consciousness, 0)
    score += cs
    if cs >= 24:
        alerts.append(f"Altered consciousness: {patient.consciousness}")

    return score, alerts


def compute_symptom_score(patient: PatientIntake) -> tuple[float, list[str]]:
    score = 0.0
    flags: list[str] = []
    high_risk_keywords = [
        "chest pain",
        "shortness of breath",
        "stroke",
        "seizure",
        "unconscious",
        "trauma",
        "bleeding",
        "cardiac",
        "anaphylaxis",
        "overdose",
        "difficulty breathing",
    ]
    moderate_risk_keywords = ["abdominal pain", "vomiting blood", "head injury", "fracture", "high fever", "severe headache", "dizziness"]
    text = (patient.chief_complaint + " " + " ".join(patient.symptoms)).lower()

    for kw in high_risk_keywords:
        if kw in text:
            score += 16
            flags.append(f"High-risk symptom: {kw}")
    for kw in moderate_risk_keywords:
        if kw in text:
            score += 8
            flags.append(f"Moderate-risk symptom: {kw}")

    if patient.pain_scale >= 9:
        score += 16
    elif patient.pain_scale >= 7:
        score += 8

    if patient.arrival_mode == "ambulance":
        score += 10
        flags.append("Arrived by ambulance")

    if patient.age < 2 or patient.age > 75:
        score += 8
        flags.append(f"Age risk factor: {patient.age} years")

    high_risk_history = ["diabetes", "cardiac", "copd", "renal", "cancer", "immunocompromised"]
    for item in patient.medical_history:
        if any(k in item.lower() for k in high_risk_history):
            score += 6
            flags.append(f"High-risk history: {item}")

    return score, flags


def score_to_esi(total_score: float) -> int:
    if total_score >= 85:
        return 1
    if total_score >= 65:
        return 2
    if total_score >= 42:
        return 3
    if total_score >= 22:
        return 4
    return 5


def compute_forecast(db: Session) -> list[dict[str, Any]]:
    beds = get_beds_state(db)
    total_beds = sum(b["total"] for b in beds)
    occupied = sum(b["occupied"] for b in beds)
    base_util = (occupied / total_beds) * 100 if total_beds else 0

    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(hours=6)
    rows = db.scalars(select(TriageEvent).where(TriageEvent.created_at >= recent_cutoff)).all()
    bucket_counts = [0, 0, 0, 0, 0, 0]
    for row in rows:
        event_time = row.created_at
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        else:
            event_time = event_time.astimezone(timezone.utc)
        delta_hours = int((now - event_time).total_seconds() // 3600)
        if 0 <= delta_hours < 6:
            bucket_counts[5 - delta_hours] += 1

    if rows:
        per_hour = len(rows) / 6.0
        trend = (bucket_counts[-1] - bucket_counts[0]) / 5.0
    else:
        per_hour = 0.0
        trend = 0.0

    forecasts: list[dict[str, Any]] = []
    for hour in range(1, 7):
        admissions = max(0, int(round(per_hour + (trend * hour))))
        predicted_util = min(98.0, base_util + (admissions * 0.9 * hour))

        risk_level = "low"
        if predicted_util > 90:
            risk_level = "critical"
        elif predicted_util > 80:
            risk_level = "high"
        elif predicted_util > 70:
            risk_level = "moderate"

        forecasts.append(
            {
                "hour": hour,
                "label": f"+{hour}h",
                "predicted_admissions": admissions,
                "predicted_utilization": round(predicted_util, 1),
                "risk_level": risk_level,
            }
        )

    return forecasts


def get_beds_state(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(select(BedSnapshot).order_by(BedSnapshot.department.asc())).all()
    state: list[dict[str, Any]] = []
    for row in rows:
        occupied = max(0, min(row.occupied, row.total))
        available = row.total - occupied
        util = round((occupied / row.total) * 100, 1) if row.total else 0.0
        state.append(
            {
                "department": row.department,
                "total": row.total,
                "occupied": occupied,
                "available": available,
                "utilization_pct": util,
                "updated_at": row.updated_at.isoformat(),
            }
        )
    return state


def compute_dashboard_stats(db: Session) -> dict[str, Any]:
    beds = get_beds_state(db)
    total_beds = sum(b["total"] for b in beds)
    occupied = sum(b["occupied"] for b in beds)
    start_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    total_today = db.scalar(select(func.count(TriageEvent.id)).where(TriageEvent.created_at >= start_day)) or 0
    critical_today = db.scalar(
        select(func.count(TriageEvent.id)).where(TriageEvent.created_at >= start_day, TriageEvent.esi_level <= 2)
    ) or 0
    avg_processing = db.scalar(select(func.avg(TriageEvent.processing_ms)).where(TriageEvent.created_at >= start_day)) or 0.0

    return {
        "total_beds": total_beds,
        "occupied_beds": occupied,
        "available_beds": total_beds - occupied,
        "overall_utilization": round((occupied / total_beds) * 100, 1) if total_beds else 0.0,
        "patients_triaged_today": int(total_today),
        "avg_triage_time_seconds": round(float(avg_processing) / 1000.0, 2),
        "critical_cases_today": int(critical_today),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def compute_live_alerts(db: Session) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    now = datetime.now(timezone.utc)

    for bed in get_beds_state(db):
        util = bed["utilization_pct"]
        if util >= 95:
            alerts.append({"type": "critical", "text": f"{bed['department']} utilization at {util}%", "time": now.strftime("%H:%M")})
        elif util >= 85:
            alerts.append({"type": "warning", "text": f"{bed['department']} nearing capacity at {util}%", "time": now.strftime("%H:%M")})

    forecast = compute_forecast(db)
    for f in forecast[:3]:
        if f["risk_level"] in {"critical", "high"}:
            alerts.append(
                {
                    "type": "critical" if f["risk_level"] == "critical" else "warning",
                    "text": f"Forecast {f['label']}: {f['predicted_utilization']}% utilization ({f['risk_level']})",
                    "time": now.strftime("%H:%M"),
                }
            )

    if not alerts:
        alerts.append({"type": "info", "text": "No critical operational alerts from live streams.", "time": now.strftime("%H:%M")})
    return alerts[:12]


def compute_traffic_snapshot(db: Session) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    one_min = now - timedelta(minutes=1)
    five_min = now - timedelta(minutes=5)
    one_hour = now - timedelta(hours=1)
    triage_last_min = db.scalar(select(func.count(TriageEvent.id)).where(TriageEvent.created_at >= one_min)) or 0
    triage_last_5m = db.scalar(select(func.count(TriageEvent.id)).where(TriageEvent.created_at >= five_min)) or 0
    triage_last_hour = db.scalar(select(func.count(TriageEvent.id)).where(TriageEvent.created_at >= one_hour)) or 0
    rpm = float(triage_last_min)
    return {
        "triage_last_minute": int(triage_last_min),
        "triage_last_5_minutes": int(triage_last_5m),
        "triage_last_hour": int(triage_last_hour),
        "requests_per_second_estimate": round(rpm / 60.0, 2),
        "active_ws_clients": len(manager.connections),
        "timestamp": now.isoformat(),
    }


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for conn in self.connections:
            try:
                await conn.send_json(message)
            except Exception:
                dead.append(conn)
        for d in dead:
            self.disconnect(d)


manager = ConnectionManager()


@app.on_event("startup")
async def startup_event() -> None:
    bootstrap_data()


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "MediTriage AI API", "status": "operational", "version": settings.api_version, "docs": "/docs"}


@app.post("/api/triage", response_model=TriageResult)
async def triage_patient(patient: PatientIntake, request: Request, db: Session = Depends(get_db), _: None = Depends(rate_limit)) -> TriageResult:
    start = time.perf_counter()
    vital_score, vital_alerts = compute_vital_score(patient)
    symptom_score, risk_flags = compute_symptom_score(patient)
    total_score = min(vital_score + symptom_score, 100.0)
    esi_level = score_to_esi(total_score)
    patient_id = f"PT-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc)

    result = TriageResult(
        patient_id=patient_id,
        esi_level=esi_level,
        esi_label=ESI_LABELS[esi_level],
        priority_score=round(total_score, 1),
        recommended_wait=ESI_WAIT[esi_level],
        recommended_department=DEPT_MAP[esi_level],
        risk_flags=risk_flags[:8],
        vital_alerts=vital_alerts[:8],
        timestamp=now.isoformat(),
    )

    processing_ms = (time.perf_counter() - start) * 1000.0
    db.add(
        TriageEvent(
            patient_id=patient_id,
            chief_complaint=patient.chief_complaint,
            esi_level=esi_level,
            priority_score=float(result.priority_score),
            recommended_department=result.recommended_department,
            processing_ms=processing_ms,
            payload=patient.model_dump(),
            result=result.model_dump(),
        )
    )
    db.commit()

    await manager.broadcast(
        {
            "event": "triage_created",
            "patient_id": patient_id,
            "esi_level": esi_level,
            "priority_score": result.priority_score,
            "timestamp": now.isoformat(),
            "source_ip": request.client.host if request.client else "unknown",
        }
    )
    return result


@app.get("/api/beds")
def get_beds(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"beds": get_beds_state(db), "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/api/beds/provision")
async def provision_beds(
    items: list[BedProvisionItem],
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    if not items:
        raise HTTPException(status_code=400, detail="At least one department is required")

    upserted = 0
    for item in items:
        if item.occupied > item.total:
            raise HTTPException(status_code=400, detail=f"Occupied cannot exceed total for {item.department}")
        row = db.scalar(select(BedSnapshot).where(BedSnapshot.department == item.department))
        if row:
            row.total = item.total
            row.occupied = item.occupied
            row.updated_at = datetime.now(timezone.utc)
        else:
            db.add(BedSnapshot(department=item.department, total=item.total, occupied=item.occupied))
        upserted += 1

    db.commit()
    payload = {"event": "beds_provisioned", "count": upserted, "timestamp": datetime.now(timezone.utc).isoformat()}
    await manager.broadcast(payload)
    return payload


@app.put("/api/beds/{department}")
async def update_bed_occupancy(
    department: str,
    update: BedUpdateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    bed = db.scalar(select(BedSnapshot).where(BedSnapshot.department == department))
    if not bed:
        raise HTTPException(status_code=404, detail="Department not found")
    if update.occupied > bed.total:
        raise HTTPException(status_code=400, detail="Occupied cannot exceed total beds")

    bed.occupied = update.occupied
    bed.updated_at = datetime.now(timezone.utc)
    db.commit()

    payload = {
        "event": "bed_updated",
        "department": bed.department,
        "occupied": bed.occupied,
        "total": bed.total,
        "timestamp": bed.updated_at.isoformat(),
    }
    await manager.broadcast(payload)
    return payload


@app.get("/api/forecast")
def get_resource_forecast(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"forecast": compute_forecast(db), "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/queue")
def get_queue(db: Session = Depends(get_db)) -> dict[str, Any]:
    events = db.scalars(select(TriageEvent).order_by(TriageEvent.esi_level.asc(), TriageEvent.created_at.asc()).limit(25)).all()
    queue = []
    for idx, ev in enumerate(events, start=1):
        queue.append(
            {
                "position": idx,
                "patient_id": ev.patient_id,
                "complaint": ev.chief_complaint,
                "esi_level": ev.esi_level,
                "esi_label": ESI_LABELS.get(ev.esi_level, "Unknown"),
                "wait": ESI_WAIT.get(ev.esi_level, "N/A"),
                "department": ev.recommended_department,
                "arrived": ev.created_at.astimezone().strftime("%H:%M"),
                "priority_score": ev.priority_score,
            }
        )
    return {"queue": queue, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    return compute_dashboard_stats(db)


@app.get("/api/alerts")
def get_alerts(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"alerts": compute_live_alerts(db), "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/ops/traffic")
def get_traffic(db: Session = Depends(get_db)) -> dict[str, Any]:
    return compute_traffic_snapshot(db)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/ready")
def readiness_check(db: Session = Depends(get_db)) -> dict[str, Any]:
    db.scalar(select(func.count(BedSnapshot.id)))
    return {"status": "ready", "database": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.websocket("/ws/updates")
async def ws_updates(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def metrics_tick() -> None:
    while True:
        await asyncio.sleep(5)
        with SessionLocal() as db:
            await manager.broadcast(
                {
                    "event": "metrics_tick",
                    "stats": compute_dashboard_stats(db),
                    "traffic": compute_traffic_snapshot(db),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )


@app.on_event("startup")
async def start_metrics_task() -> None:
    asyncio.create_task(metrics_tick())


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
