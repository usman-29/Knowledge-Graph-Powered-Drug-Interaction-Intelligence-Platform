# Clinical Drug-Safety Orchestrator — Frontend

Next.js 15 (App Router) frontend for the Autonomous Clinical Discharge & Care-Plan Orchestrator.

## Stack

- **Next.js 15** App Router + Server Components
- **TypeScript** strict mode
- **Tailwind CSS + shadcn/ui** primitives (neutral, professional palette)
- **Auth.js v5** with credentials provider + JWT sessions
- **better-sqlite3** for the local users table (zero setup)
- **next-themes** for light/dark toggle

## Architecture

```
Browser ──► Next.js ──► FastAPI (server/) ──► Lobster Trap (proxy) ──► LLM
                │
                ├── SQLite (users + sessions)
                └── Auth.js (JWT cookies)
```

The browser only ever talks to Next.js. Every backend call is proxied
through a Next.js API route that checks the session first.

## Setup

```bash
cd client
npm install
cp .env.local.example .env.local
# Generate a strong AUTH_SECRET:
#   openssl rand -base64 32
# Paste it into .env.local
```

## Run

In three terminals:

```bash
# 1. Lobster Trap (LLM proxy)
cd ..  # repo root
./lobstertrap serve --backend https://router.huggingface.co/featherless-ai --policy server/configs/lobster_policy.yaml

# 2. FastAPI backend
cd server && source venv/bin/activate && source .env && uvicorn main:app --reload

# 3. Next.js frontend
cd client && npm run dev
```

Open http://localhost:3000.

## Pages

| Route | Access | What it does |
|---|---|---|
| `/login`, `/register` | Public | Auth |
| `/chat` | Any signed-in user | Main drug-safety chat |
| `/admin` | ADMIN only | Overview stats |
| `/admin/logs` | ADMIN only | Audit log viewer with full trace details |
| `/admin/users` | ADMIN only | Registered users list |

## How auth + RBAC fit together

1. User registers with email + password + role on `/register`.
2. We hash the password and create a row in the **local SQLite** `users` table.
3. The new user's id is also POSTed to the **backend's `/admin/users`** endpoint to mirror the role into the FastAPI in-memory RBAC registry.
4. On every `/chat` request the Next.js API route forwards `user_id` to the FastAPI backend, which re-derives the role and runs the `access_control_node`.

Login uses Auth.js JWT sessions stored in a httpOnly cookie. Middleware in
[middleware.ts](middleware.ts) protects every page; `/admin/*` additionally
requires `role=ADMIN`.

## Files

```
client/
├── app/
│   ├── (auth)/            # login + register pages
│   ├── (dashboard)/       # chat + admin (auth-protected)
│   ├── api/               # route handlers (auth, chat proxy, admin proxies)
│   ├── layout.tsx         # ThemeProvider + Toaster
│   └── globals.css
├── components/
│   ├── ui/                # shadcn primitives
│   ├── chat/              # ChatInterface, Markdown renderer
│   ├── admin/             # StatsCards, LogsTable
│   └── layout/            # Sidebar, theme toggle/provider
├── lib/
│   ├── auth.ts            # Auth.js config
│   ├── backend.ts         # FastAPI client
│   ├── db.ts              # SQLite users table
│   └── utils.ts           # cn() + time helpers
├── middleware.ts          # route protection
└── data/client.sqlite     # auto-created on first run
```
