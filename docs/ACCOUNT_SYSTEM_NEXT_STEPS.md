# Bassly Account System Next Steps

This file describes the easiest path from the current Flask site to the final platform:

- public website
- customer accounts
- DJ accounts
- one admin account
- PostgreSQL database
- online deployment

## What is already prepared in code

- `users` table
- `customers` table
- `djs` table
- existing `booking` table extended with optional links to customers and DJs
- default admin user seeding from:
  - `MANAGER_USERNAME`
  - `MANAGER_PASSWORD`
  - `MANAGER_EMAIL`

## Tool by tool

### 1. Supabase

Use Supabase for the hosted PostgreSQL database.

Steps:
1. Create a new project.
2. Save the database password somewhere safe.
3. Open `Project Settings` -> `Database`.
4. Copy the PostgreSQL connection string / URI.

You will use that URI later as `DATABASE_URL` in Render.

### 2. DBeaver

Use DBeaver to inspect the database visually.

Steps:
1. Create a new PostgreSQL connection.
2. Paste the host, database, username, password, and port from Supabase.
3. Test the connection.
4. Save it.

After the app connects to Supabase, you should see:
- `users`
- `customers`
- `djs`
- `booking`
- `dj_application`
- `dj_status`

### 3. VS Code

Use VS Code for the next code steps.

Recommended order:
1. Build `/register`
2. Build `/login`
3. Build `/logout`
4. Build role checks:
   - customer
   - dj
   - admin
5. Link new bookings to logged-in customers
6. Link DJ profiles to logged-in DJ users

### 4. Render

Use Render for the public website.

Environment variables to set:
- `SECRET_KEY`
- `DATABASE_URL`
- `MANAGER_USERNAME`
- `MANAGER_PASSWORD`
- `MANAGER_EMAIL`

Optional mail variables:
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `MANAGER_NOTIFY_EMAIL`

## Recommended build order

### Phase 1
- real users table
- real customer profiles
- real DJ profiles
- seeded admin account

### Phase 2
- register/login/logout
- customer dashboard
- DJ dashboard

### Phase 3
- bookings created by logged-in customers
- DJ approval flow
- admin-only review flow

### Phase 4
- file storage migration
- online deployment
- custom domain

## Temporary note

The current site still works with the existing public booking flow and manager flow.
The new tables are prepared so the next login/account steps can be added safely.
