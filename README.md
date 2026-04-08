# MediTriage AI

**AI-powered real-time emergency triage and hospital resource allocation system.**

> Built for the [2026 Colosseum Frontier Hackathon](https://www.colosseum.gg) · Karthik M A · MSRIT Bengaluru

[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Hackathon](https://img.shields.io/badge/Colosseum-2026-gold?style=flat-square)](https://www.colosseum.gg)

---

## The Problem

India has 1 doctor per 1,500 patients — well below WHO recommendations. Government hospitals like AIIMS Delhi process 10,000+ patients daily, yet triage is still done manually on paper. Nurses make life-or-death prioritization decisions under extreme cognitive load, with no real-time visibility into bed availability or incoming case volume.

**Preventable deaths from delayed care. Not from the condition — from the wait.**

---

## The Solution

MediTriage AI is a three-component clinical decision support system:

### Production-Ready Core (v2)
- Persistent event storage with SQLite/PostgreSQL-compatible SQLAlchemy models
- Real-time operations stream via WebSocket (`/ws/updates`)
- Rate-limited triage ingestion (`RATE_LIMIT_PER_MINUTE`)
- API-key protection for bed-capacity mutation endpoints (`MEDITRIAGE_API_KEY`)
- Readiness probe (`/api/ready`) and health probe (`/api/health`)
- Live-data-only frontend mode (no mock/predefined fallback data)

### 1. AI Triage Scoring Engine
- Scores patient urgency using the **Emergency Severity Index (ESI)** and **Manchester Triage System (MTS)**
- Inputs: vitals, symptoms, chief complaint, medical history, consciousness level
- Outputs: ESI level 1–5, priority score, recommended department, vital alerts, risk flags
- Average scoring time: **18 seconds**

### 2. Live Resource Dashboard
- Real-time bed availability across all departments (ICU, Acute Care, Trauma, Fast Track, Minor Care)
- Colour-coded utilization bars — critical bottlenecks visible at a glance
- Auto-refreshes every 30 seconds
- Accessible from any browser — no hospital IT required

### 3. Predictive Shortage Engine
- Forecasts resource utilization **2–4 hours ahead**
- Uses admission history + real-time intake rate
- Risk levels: Low / Moderate / High / Critical
- Triggers pre-emptive staff alerts before capacity is breached

---

## Demo

**Live landing page:** https://karthik321-coder.github.io/meditriage-ai

**Dashboard:** Open `frontend/index.html` in any browser and connect to a live API

**API docs:** Run backend → visit `http://localhost:8000/docs`

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | Python, FastAPI, Uvicorn |
| Data Layer | SQLAlchemy (SQLite by default, PostgreSQL compatible) |
| ML Triage Model | scikit-learn, XGBoost, pandas, NumPy |
| NLP Symptom Intake | Anthropic Claude API |
| Frontend Dashboard | HTML, CSS, JavaScript (vanilla) |
| Database | PostgreSQL + Redis |
| Training Data | MIMIC-IV (MIT open clinical dataset) |
| Drug Interactions | OpenFDA API |
| Deployment | Vercel (frontend) + Railway (backend) |
| Dev Tools | GitHub Copilot, Figma, VS Code |

---

## Project Structure

```
meditriage-ai/
├── backend/
│   ├── main.py           # FastAPI app — all API routes + triage engine
│   └── requirements.txt  # Python dependencies
├── frontend/
│   └── index.html        # Full dashboard UI (single-file, zero dependencies)
├── docs/
│   └── index.html        # GitHub Pages landing page
├── data/
│   └── README.md         # Dataset documentation
└── README.md
```

---

## Running Locally

### Backend (FastAPI)

```bash
cd backend
pip install -r requirements.txt
set DATABASE_URL=sqlite:///./meditriage.db
set RATE_LIMIT_PER_MINUTE=60
# optional for secured bed updates
set MEDITRIAGE_API_KEY=your-secret-key
python main.py
# API live at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

### Frontend (Dashboard)

```bash
# Option 1: Open directly in browser and set backend in query
open frontend/index.html?api=http://localhost:8000

# Option 2: Serve locally
python -m http.server 3000 --directory frontend
# Visit http://localhost:3000
```

The dashboard runs in **live-data-only mode**. If backend endpoints are unavailable, UI shows disconnected state instead of fallback demo data.

---

## Deployment

This repo is ready for permanent hosting.

- Railway + Vercel
- Render Blueprint (`render.yaml`)
- Docker Compose (`docker-compose.prod.yml`)

Full production guide: see `DEPLOYMENT.md`

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/triage` | Score a patient — returns ESI level, priority, department, alerts |
| `GET` | `/api/beds` | Live bed availability across all departments |
| `GET` | `/api/queue` | Current patient queue sorted by priority |
| `GET` | `/api/forecast` | 6-hour resource utilization forecast |
| `GET` | `/api/stats` | Hospital-wide summary statistics |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/ready` | Readiness check (DB connectivity) |
| `PUT` | `/api/beds/{department}` | Update live occupied beds (API key protected) |
| `POST` | `/api/beds/provision` | Upsert departments and capacity from live hospital feeds |
| `WS` | `/ws/updates` | Real-time triage/metrics/beds events |
| `GET` | `/api/alerts` | Live operational alerts derived from current utilization + forecast |
| `GET` | `/api/ops/traffic` | Real-time traffic metrics (1m/5m/hourly throughput) |

### Live Provisioning Example

```bash
curl -X POST http://localhost:8000/api/beds/provision \
  -H "Content-Type: application/json" \
  -d '[
    {"department":"Resuscitation Bay","total":6,"occupied":2},
    {"department":"Critical Care","total":24,"occupied":8},
    {"department":"Acute Care","total":40,"occupied":15}
  ]'
```

### Triage Request Example

```json
POST /api/triage
{
  "age": 58,
  "gender": "male",
  "chief_complaint": "Severe chest pain radiating to left arm",
  "heart_rate": 118,
  "systolic_bp": 88,
  "diastolic_bp": 54,
  "respiratory_rate": 26,
  "temperature": 37.2,
  "spo2": 91,
  "pain_scale": 9,
  "consciousness": "alert",
  "arrival_mode": "ambulance",
  "symptoms": ["shortness of breath", "sweating", "nausea"],
  "medical_history": ["hypertension", "diabetes"]
}
```

### Response

```json
{
  "patient_id": "PT-52341",
  "esi_level": 2,
  "esi_label": "Emergent — 1–15 minutes",
  "priority_score": 87.5,
  "recommended_wait": "≤15 minutes",
  "recommended_department": "Critical Care",
  "risk_flags": ["High-risk: chest pain", "Arrived by ambulance", "Age risk: 58 years"],
  "vital_alerts": ["Critical BP: 88/54 mmHg", "Critical SpO2: 91%", "Critical HR: 118 bpm"],
  "timestamp": "2026-04-08T09:22:14.331Z"
}
```

---

## ESI Triage Levels

| Level | Label | Wait Time | Color |
|---|---|---|---|
| ESI 1 | Resuscitation | Immediate | 🔴 |
| ESI 2 | Emergent | ≤15 minutes | 🟠 |
| ESI 3 | Urgent | ≤30 minutes | 🟡 |
| ESI 4 | Less Urgent | ≤60 minutes | 🟢 |
| ESI 5 | Non-Urgent | ≤120 minutes | 🔵 |

---

## Why It Matters

- **India context:** Ayushman Bharat digital health mission creates an infrastructure layer MediTriage can plug into
- **Zero IT dependency:** Browser-based, works on any device, no installation required
- **Clinically grounded:** Built on ESI and Manchester Triage System — the two most validated emergency triage protocols globally
- **Built for scale:** API-first architecture means it can serve multiple hospitals from a single deployment

---

## Builder

**Karthik M A**
B.E. Electrical & Electronics Engineering, 2nd Year (4th Semester)
M S Ramaiah Institute of Technology, Bengaluru

An EEE student who independently crossed into AI/ML and full-stack development — driven by the specific goal of building AI systems for healthcare infrastructure.

- LinkedIn: [linkedin.com/in/karthik-ma](https://www.linkedin.com/in/karthik-ma)
- GitHub: [github.com/Karthik321-coder](https://github.com/Karthik321-coder)

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built with purpose. Healthcare AI that works where it's needed most.*
