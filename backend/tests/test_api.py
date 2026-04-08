from fastapi.testclient import TestClient

from main import app, bootstrap_data


bootstrap_data()


def get_client() -> TestClient:
    return TestClient(app)


def test_health_endpoint() -> None:
    with get_client() as client:
        res = client.get("/api/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "healthy"


def test_ready_endpoint() -> None:
    with get_client() as client:
        res = client.get("/api/ready")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ready"


def test_triage_endpoint_live_payload() -> None:
    payload = {
        "age": 54,
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
        "medical_history": ["hypertension", "diabetes"],
    }

    with get_client() as client:
        res = client.post("/api/triage", json=payload)
        assert res.status_code == 200
        body = res.json()
        assert body["patient_id"].startswith("PT-")
        assert 1 <= body["esi_level"] <= 5
        assert body["recommended_department"]


def test_bed_provision_and_fetch() -> None:
    provision = [
        {"department": "Resuscitation Bay", "total": 6, "occupied": 2},
        {"department": "Critical Care", "total": 24, "occupied": 8},
    ]
    with get_client() as client:
        res = client.post("/api/beds/provision", json=provision)
        assert res.status_code == 200

        beds = client.get("/api/beds")
        assert beds.status_code == 200
        body = beds.json()
        assert isinstance(body.get("beds"), list)
        assert any(b["department"] == "Resuscitation Bay" for b in body["beds"])


def test_alerts_and_forecast_endpoints() -> None:
    with get_client() as client:
        forecast = client.get("/api/forecast")
        assert forecast.status_code == 200
        fc_body = forecast.json()
        assert len(fc_body.get("forecast", [])) == 6

        alerts = client.get("/api/alerts")
        assert alerts.status_code == 200
        alert_body = alerts.json()
        assert isinstance(alert_body.get("alerts"), list)


def test_validation_error_for_bad_payload() -> None:
    with get_client() as client:
        res = client.post("/api/triage", json={"age": 999})
        assert res.status_code == 422
