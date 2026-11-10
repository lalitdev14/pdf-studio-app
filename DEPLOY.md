# Deploying: Vercel (frontend) + Render (backend)

The API needs LibreOffice, Tesseract and Poppler, so it runs as a Docker service on Render.
The React site is a static build on Vercel and calls the API at `VITE_API_BASE`.

## 1. Backend on Render
1. Render dashboard → **New → Blueprint** → pick this GitHub repo. It reads `render.yaml`.
2. When asked for `CORS_ORIGINS`, enter your Vercel URL (e.g. `https://pdf-studio.vercel.app`).
   You can fill it in after step 2 and redeploy.
3. Wait for the deploy, then open `https://<your-service>.onrender.com/api/health`. It should return `"status":"ok"`.

## 2. Frontend on Vercel
1. Vercel → **Add New → Project** → import this GitHub repo.
2. Set **Root Directory** to `frontend` (framework: Vite, auto-detected).
3. Add the environment variable `VITE_API_BASE` = `https://<your-service>.onrender.com` (no trailing slash).
4. Deploy. Every push to `main` redeploys both services automatically.

If you change the Vercel domain, update `CORS_ORIGINS` on Render. If you change the Render URL, update `VITE_API_BASE` on Vercel and redeploy.

## Notes on Render's free plan
- The service sleeps after ~15 minutes idle; the first request after that takes ~1 minute.
- There is no persistent disk: uploaded files are temporary anyway (deleted after 60 min),
  but **user accounts and saved files are lost on each restart/redeploy**. Add a Render disk
  mounted at `/data` (paid plan) if you need accounts to persist.
