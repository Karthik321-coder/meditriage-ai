# MediTriage Production Deployment

This repository is now prepared for both temporary public sharing and permanent cloud deployment.

## 1) Instant public URL (already live)

Frontend:
https://caring-scenarios-works-clay.trycloudflare.com/frontend/index.html?api=https://tackle-thee-grande-provinces.trycloudflare.com

Backend:
https://tackle-thee-grande-provinces.trycloudflare.com

Note: these quick tunnel URLs are temporary and change on restart.

## 2) Permanent deployment option A (Railway backend + Vercel frontend)

### Backend on Railway
1. Push this repo to GitHub.
2. Create Railway project from GitHub repo.
3. Set root directory to backend.
4. Railway uses backend/Dockerfile.
5. Add environment variables:
   - DATABASE_URL (recommended PostgreSQL URL from Railway plugin)
   - RATE_LIMIT_PER_MINUTE=300
   - MEDITRIAGE_API_KEY=your-secret
   - ALLOWED_ORIGINS=https://your-frontend-domain.vercel.app
6. Deploy and copy backend URL.

### Frontend on Vercel
1. Import this repo in Vercel.
2. Set root directory to frontend.
3. Deploy.
4. Open deployed URL with backend query parameter:
   - https://your-frontend-domain.vercel.app/?api=https://your-backend-domain.railway.app

## 3) Permanent deployment option B (Render full stack)

Use render.yaml in repo root.

1. Connect GitHub repo in Render.
2. Select Blueprint deploy.
3. Render will create:
   - meditriage-backend (Docker)
   - meditriage-frontend (Docker)
4. Set backend env vars in Render dashboard:
   - DATABASE_URL (PostgreSQL recommended)
   - RATE_LIMIT_PER_MINUTE=300
   - MEDITRIAGE_API_KEY=your-secret
   - ALLOWED_ORIGINS=https://your-frontend-domain.onrender.com

## 4) Containerized self-host deployment

Run both services with Docker Compose:

1. docker compose -f docker-compose.prod.yml up --build -d
2. Frontend: http://localhost:8080
3. Backend: http://localhost:8000

## 5) Live data provisioning after deploy

Provision departments before dashboard operations:

curl -X POST https://your-backend-domain/api/beds/provision \
  -H "Content-Type: application/json" \
  -d '[
    {"department":"Resuscitation Bay","total":6,"occupied":2},
    {"department":"Critical Care","total":24,"occupied":8},
    {"department":"Acute Care","total":40,"occupied":15}
  ]'

## 6) Production checklist

- Use managed PostgreSQL, not SQLite, in production.
- Set strong MEDITRIAGE_API_KEY.
- Restrict ALLOWED_ORIGINS to your frontend domain.
- Enable HTTPS-only in hosting platform.
- Monitor /api/health and /api/ready.
- Use /api/ops/traffic for live throughput dashboards.
