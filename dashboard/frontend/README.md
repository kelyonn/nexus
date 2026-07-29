Next.js control panel for `nexus dashboard` (PRD §10, §13).

## Two build modes

- **Frontend development** (hot reload, talks to a separately-running
  backend on port 3002):

  ```bash
  npm install
  npm run dev   # http://localhost:3001
  ```

  `next.config.ts` rewrites `/api/*` to `NEXUS_DASHBOARD_BACKEND`
  (default `http://127.0.0.1:3002`) in this mode.

- **What `nexus dashboard` actually ships** — a static export, with no
  Node runtime needed by the end user:

  ```bash
  NEXUS_STATIC_EXPORT=1 npm run build   # writes ./out
  ```

  The FastAPI backend (`dashboard/backend/main.py` + `static.py`) serves
  `out/` directly alongside its own `/api/*` routes — one process, same
  origin, no rewrite needed. This is what the project's hatchling build
  hook (`../../hatch_build.py`) runs automatically when packaging a wheel;
  Node is a maintainer-time requirement for that, not a user-time one for
  `pip install`.

If you're working on this repo from a checkout, run the static build once
before `nexus dashboard` will find anything at `dashboard/frontend/out/`
(`core/dashboard.check_frontend_built()` tells you this with the exact
command if you forget).

## Routes

- `/` — Overview grid of every Nexus-managed app.
- `/apps?name=<app>` — App Detail. A query param, not a dynamic segment
  (`/apps/[name]`) — static export can't serve arbitrary dynamic routes
  without knowing every app name at build time, so this reads `?name=`
  client-side with `useSearchParams` instead (wrapped in `<Suspense>`,
  which static builds require for that hook).
- `/synclog` — GitOps sync log across all apps.
