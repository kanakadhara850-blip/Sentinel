# SENTINEL: Real-Time AI-Powered Transaction Risk Intelligence

Static, zero-build site: landing page, demo login, role-based dashboard.
Files: `public/index.html` (the whole app), `vercel.json` (rewrites + security headers).

## Demo accounts (password: `sentinel-demo`)
admin@sentinel.demo, security@sentinel.demo, fraud@sentinel.demo, auditor@sentinel.demo, viewer@sentinel.demo
Auth is a frontend-only demo (credentials are readable in the browser). Replace the `Auth.provider` object with a real provider before production.

## Run locally
`cd public && python3 -m http.server 3000` then open http://localhost:3000 (deep links like /dashboard need Vercel or `npx vercel dev`).

## Deploy to Vercel
1. Push this folder to a GitHub repo (`git init && git add . && git commit -m init && git push`).
2. vercel.com, Add New, Project, import the repo.
3. Framework Preset: **Other**. Build Command: empty. Output Directory: **public**. Install Command: empty.
4. Deploy. Open the URL: landing page, then Sign in.

CLI: `npm i -g vercel && vercel --prod` (answer `public` for the output directory).

## Live mode
Open `/dashboard?ws=wss://your-backend/ws/events` (use wss:// on HTTPS). The backend must send the JSON shape in the original README. Vercel cannot host Kafka, Redis, SQLite or Python workers; run the backend elsewhere.
