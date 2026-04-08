from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List
import uvicorn
import random
import math
from datetime import datetime, timedelta
import json

app = FastAPI(
    title="MediTriage AI API",
    description="Real-time AI-powered emergency triage and hospital resource allocation system",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic Models ────────────────────────────────────────────────────────────

class PatientIntake(BaseModel):
    age: int = Field(..., ge=0, le=120)
    gender: str = Field(..., pattern="^(male|female|other)$")
    chief_complaint: str
    heart_rate: int = Field(..., ge=20, le=300)
    systolic_bp: int = Field(..., ge=50, le=300)
    diastolic_bp: int = Field(..., ge=30, le=200)
    respiratory_rate: int = Field(..., ge=4, le=60)
    temperature: float = Field(..., ge=30.0, le=45.0)
    spo2: int = Field(..., ge=50, le=100)
    pain_scale: int = Field(..., ge=0, le=10)
    consciousness: str = Field(..., pattern="^(alert|verbal|pain|unresponsive)$")
    arrival_mode: str = Field(..., pattern="^(walk-in|ambulance|referred)$")
    symptoms: List[str] = []
    medical_history: Optional[List[str]] = []

class TriageResult(BaseModel):
    patient_id: str
    esi_level: int
    esi_label: str
    priority_score: float
    recommended_wait: str
    recommended_department: str
    risk_flags: List[str]
    vital_alerts: List[str]
    timestamp: str

class BedStatus(BaseModel):
    department: str
    total: int
    occupied: int
    available: int
    utilization_pct: float

class ResourceForecast(BaseModel):
    hour: int
    predicted_admissions: int
    predicted_utilization: float
    risk_level: str

# ── Triage Scoring Engine ──────────────────────────────────────────────────────

ESI_LABELS = {
    1: "Resuscitation — Immediate",
    2: "Emergent — 1–15 minutes",
    3: "Urgent — 30 minutes",
    4: "Less Urgent — 60 minutes",
    5: "Non-Urgent — 120+ minutes"
}

ESI_WAIT = {
    1: "Immediate",
    2: "≤15 minutes",
    3: "≤30 minutes",
    4: "≤60 minutes",
    5: "≤120 minutes"
}

DEPT_MAP = {
    1: "Resuscitation Bay",
    2: "Critical Care",
    3: "Acute Care",
    4: "Fast Track",
    5: "Minor Care"
}

def compute_vital_score(patient: PatientIntake) -> tuple[float, list]:
    score = 0.0
    alerts = []

    # Heart rate scoring
    if patient.heart_rate < 50 or patient.heart_rate > 150:
        score += 30
        alerts.append(f"Critical HR: {patient.heart_rate} bpm")
    elif patient.heart_rate < 60 or patient.heart_rate > 120:
        score += 15
        alerts.append(f"Abnormal HR: {patient.heart_rate} bpm")

    # Blood pressure scoring
    if patient.systolic_bp < 90 or patient.systolic_bp > 180:
        score += 30
        alerts.append(f"Critical BP: {patient.systolic_bp}/{patient.diastolic_bp} mmHg")
    elif patient.systolic_bp < 100 or patient.systolic_bp > 160:
        score += 15
        alerts.append(f"Abnormal BP: {patient.systolic_bp}/{patient.diastolic_bp} mmHg")

    # SpO2 scoring
    if patient.spo2 < 90:
        score += 35
        alerts.append(f"Critical SpO2: {patient.spo2}%")
    elif patient.spo2 < 95:
        score += 20
        alerts.append(f"Low SpO2: {patient.spo2}%")

    # Respiratory rate
    if patient.respiratory_rate < 8 or patient.respiratory_rate > 30:
        score += 30
        alerts.append(f"Critical RR: {patient.respiratory_rate}/min")
    elif patient.respiratory_rate < 12 or patient.respiratory_rate > 24:
        score += 15

    # Temperature
    if patient.temperature > 40.0 or patient.temperature < 35.0:
        score += 25
        alerts.append(f"Critical Temp: {patient.temperature}°C")
    elif patient.temperature > 38.5 or patient.temperature < 36.0:
        score += 10

    # Consciousness
    consciousness_score = {"alert": 0, "verbal": 20, "pain": 40, "unresponsive": 60}
    cs = consciousness_score.get(patient.consciousness, 0)
    score += cs
    if cs >= 40:
        alerts.append(f"Altered consciousness: {patient.consciousness}")

    return score, alerts

def compute_symptom_score(patient: PatientIntake) -> tuple[float, list]:
    score = 0.0
    risk_flags = []

    high_risk_keywords = [
        "chest pain", "shortness of breath", "stroke", "seizure",
        "unconscious", "trauma", "bleeding", "cardiac", "anaphylaxis",
        "overdose", "poisoning", "severe pain", "difficulty breathing"
    ]
    moderate_risk_keywords = [
        "abdominal pain", "vomiting blood", "head injury", "fracture",
        "high fever", "severe headache", "back pain", "dizziness"
    ]

    complaint_lower = patient.chief_complaint.lower()
    symptoms_lower = [s.lower() for s in patient.symptoms]
    all_text = complaint_lower + " " + " ".join(symptoms_lower)

    for kw in high_risk_keywords:
        if kw in all_text:
            score += 25
            risk_flags.append(f"High-risk symptom: {kw}")

    for kw in moderate_risk_keywords:
        if kw in all_text:
            score += 10
            risk_flags.append(f"Moderate-risk symptom: {kw}")

    # Pain scale
    if patient.pain_scale >= 9:
        score += 20
    elif patient.pain_scale >= 7:
        score += 10

    # Arrival mode
    if patient.arrival_mode == "ambulance":
        score += 15
        risk_flags.append("Arrived by ambulance")

    # Age risk
    if patient.age < 2 or patient.age > 75:
        score += 10
        risk_flags.append(f"Age risk factor: {patient.age} years")

    # Medical history risk
    high_risk_history = ["diabetes", "cardiac", "copd", "renal", "cancer", "immunocompromised"]
    for h in (patient.medical_history or []):
        if any(r in h.lower() for r in high_risk_history):
            score += 8
            risk_flags.append(f"High-risk history: {h}")

    return score, risk_flags

def score_to_esi(total_score: float) -> int:
    if total_score >= 100:
        return 1
    elif total_score >= 70:
        return 2
    elif total_score >= 40:
        return 3
    elif total_score >= 20:
        return 4
    else:
        return 5

# ── Simulated Hospital State ───────────────────────────────────────────────────

def get_hospital_state():
    beds = [
        {"department": "Resuscitation Bay", "total": 4, "occupied": random.randint(2, 4)},
        {"department": "Critical Care (ICU)", "total": 20, "occupied": random.randint(14, 19)},
        {"department": "Acute Care", "total": 40, "occupied": random.randint(25, 38)},
        {"department": "Fast Track", "total": 30, "occupied": random.randint(15, 28)},
        {"department": "Minor Care", "total": 25, "occupied": random.randint(8, 20)},
        {"department": "Trauma Bay", "total": 6, "occupied": random.randint(2, 5)},
    ]
    result = []
    for b in beds:
        available = b["total"] - b["occupied"]
        result.append({
            "department": b["department"],
            "total": b["total"],
            "occupied": b["occupied"],
            "available": available,
            "utilization_pct": round((b["occupied"] / b["total"]) * 100, 1)
        })
    return result

def get_forecast():
    forecasts = []
    base_util = random.uniform(65, 80)
    for hour in range(1, 7):
        # Simulate peak hours effect
        hour_of_day = (datetime.now().hour + hour) % 24
        peak_factor = 1.0
        if 8 <= hour_of_day <= 12:
            peak_factor = 1.25
        elif 18 <= hour_of_day <= 22:
            peak_factor = 1.35
        elif 0 <= hour_of_day <= 5:
            peak_factor = 0.75

        predicted_util = min(98, base_util * peak_factor + random.uniform(-3, 3))
        predicted_admissions = int(random.randint(3, 8) * peak_factor)

        risk = "low"
        if predicted_util > 90:
            risk = "critical"
        elif predicted_util > 80:
            risk = "high"
        elif predicted_util > 70:
            risk = "moderate"

        forecasts.append({
            "hour": hour,
            "label": f"+{hour}h",
            "predicted_admissions": predicted_admissions,
            "predicted_utilization": round(predicted_util, 1),
            "risk_level": risk
        })
    return forecasts

def get_live_queue():
    complaints = [
        ("Chest pain, shortness of breath", 2, "Critical Care"),
        ("High fever, body ache", 4, "Acute Care"),
        ("Fracture, fall injury", 3, "Acute Care"),
        ("Abdominal pain, nausea", 3, "Fast Track"),
        ("Minor laceration", 5, "Minor Care"),
        ("Severe headache, dizziness", 3, "Acute Care"),
        ("Allergic reaction, rash", 4, "Fast Track"),
        ("Cardiac arrest (incoming)", 1, "Resuscitation Bay"),
    ]
    queue = []
    for i, (complaint, esi, dept) in enumerate(complaints[:random.randint(4, 8)]):
        wait = ["Immediate", "≤15 min", "≤30 min", "≤60 min", "≤120 min"][esi - 1]
        queue.append({
            "position": i + 1,
            "patient_id": f"PT-{random.randint(1000, 9999)}",
            "complaint": complaint,
            "esi_level": esi,
            "esi_label": ESI_LABELS[esi],
            "wait": wait,
            "department": dept,
            "wait_minutes": random.randint(0, 90),
            "arrived": (datetime.now() - timedelta(minutes=random.randint(5, 120))).strftime("%H:%M")
        })
    queue.sort(key=lambda x: x["esi_level"])
    return queue

# ── API Routes ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "MediTriage AI API v1.0", "status": "operational", "docs": "/docs"}

@app.post("/api/triage", response_model=TriageResult)
def triage_patient(patient: PatientIntake):
    vital_score, vital_alerts = compute_vital_score(patient)
    symptom_score, risk_flags = compute_symptom_score(patient)
    total_score = vital_score + symptom_score
    esi_level = score_to_esi(total_score)
    patient_id = f"PT-{random.randint(10000, 99999)}"

    return TriageResult(
        patient_id=patient_id,
        esi_level=esi_level,
        esi_label=ESI_LABELS[esi_level],
        priority_score=round(min(total_score, 100), 1),
        recommended_wait=ESI_WAIT[esi_level],
        recommended_department=DEPT_MAP[esi_level],
        risk_flags=risk_flags[:5],
        vital_alerts=vital_alerts[:5],
        timestamp=datetime.now().isoformat()
    )

@app.get("/api/beds")
def get_beds():
    return {"beds": get_hospital_state(), "timestamp": datetime.now().isoformat()}

@app.get("/api/forecast")
def get_resource_forecast():
    return {"forecast": get_forecast(), "timestamp": datetime.now().isoformat()}

@app.get("/api/queue")
def get_queue():
    return {"queue": get_live_queue(), "timestamp": datetime.now().isoformat()}

@app.get("/api/stats")
def get_stats():
    beds = get_hospital_state()
    total_beds = sum(b["total"] for b in beds)
    occupied = sum(b["occupied"] for b in beds)
    return {
        "total_beds": total_beds,
        "occupied_beds": occupied,
        "available_beds": total_beds - occupied,
        "overall_utilization": round((occupied / total_beds) * 100, 1),
        "patients_triaged_today": random.randint(180, 320),
        "avg_triage_time_seconds": random.randint(12, 28),
        "critical_cases_today": random.randint(8, 22),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
