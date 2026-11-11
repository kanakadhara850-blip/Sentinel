# SENTINEL
- `public/index.html`: cinematic landing page (canvas network, scroll story, simulated demo data)
- `public/app.html`: dashboard app (login, role-based routes, demo/live stream). Served for /login, /dashboard, /queue, /audit, /system via vercel.json
Demo login: admin@sentinel.demo / sentinel-demo (frontend-only demo auth; replace `Auth.provider` before production).
Deploy: push to GitHub, import in Vercel, Framework Other, no build. vercel.json sets output `public`.
Live mode: /dashboard?ws=wss://your-backend/ws/events
