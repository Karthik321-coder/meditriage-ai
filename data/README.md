# Data

## Training Dataset

MediTriage AI uses the **MIMIC-IV** (Medical Information Mart for Intensive Care) dataset for model training and validation.

- **Source:** MIT Laboratory for Computational Physiology
- **Access:** https://physionet.org/content/mimiciv/
- **License:** PhysioNet Credentialed Health Data License 1.5.0
- **Size:** ~300,000 de-identified ICU admissions

Due to PhysioNet data use agreement, raw dataset files are not included in this repository.

## Clinical Protocols Reference

- **ESI (Emergency Severity Index):** https://www.ahrq.gov/research/findings/final-reports/esi/index.html
- **Manchester Triage System:** https://www.triagenet.net/

## Synthetic Demo Data

The API uses a realistic synthetic simulation engine for demo purposes. See `backend/main.py` → `get_hospital_state()`, `get_forecast()`, and `get_live_queue()` for the simulation logic.
