# Supabase + Render Setup

This is the easiest way to run Bassly online with Supabase as the database.

## 1. Local `.env`

Create a file named `.env` in the project root and copy the values from `.env.example`.

Minimum local version:

```env
SECRET_KEY=dev-secret
MANAGER_USERNAME=managertim
MANAGER_PASSWORD=managertim132
MANAGER_EMAIL=manager@bassly.local
DATABASE_URL=
UPLOAD_BACKEND=local
```

If `DATABASE_URL` is empty, the app uses local SQLite (`bassly.db`).
If `DATABASE_URL` contains your Supabase PostgreSQL URI, the app uses Supabase.

## 2. Supabase database connection

Open your Supabase project and click `Connect`.

Use either:
- `Direct`
- or `ORM`

Take the PostgreSQL URI and place it in:
- local `.env` as `DATABASE_URL`
- Render environment variable `DATABASE_URL`

Example:

```text
postgresql://postgres:[YOUR-PASSWORD]@db.xxxxx.supabase.co:5432/postgres
```

## 3. pgAdmin / DBeaver fields

If you want to connect visually:

- Host: the part after `@` and before `:5432`
- Port: `5432`
- Database: `postgres`
- Username: `postgres`
- Password: the password you chose in Supabase

If SSL is required in pgAdmin, use:
- SSL mode: `require`

## 4. Render environment variables

In Render, set:

- `DATABASE_URL` = Supabase PostgreSQL URI
- `SECRET_KEY` = any strong secret
- `MANAGER_USERNAME` = `managertim`
- `MANAGER_PASSWORD` = your chosen manager password
- `MANAGER_EMAIL` = your manager email
- `UPLOAD_BACKEND` = `local`

Optional:
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `MANAGER_NOTIFY_EMAIL`

## 5. Important note about uploads

`UPLOAD_BACKEND=local` means profile images are still stored on the local filesystem.

That works for local development, but on Render this is not durable long-term.

So for production:
- database = ready for Supabase
- uploads = still temporary/local

The next upgrade after this should be moving uploads to Supabase Storage.
