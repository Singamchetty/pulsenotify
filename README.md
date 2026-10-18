# PulseNotify – Flight Price Monitor & Alert System

Django + DRF backend. Users set price alerts for routes (e.g. `DEL-BOM`); a Celery Beat job checks an internal mock
price feed every 60 seconds and fires an async notification when the price drops to or below the threshold.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then edit: set DJANGO_SECRET_KEY and POSTGRES_PASSWORD
docker compose up -d        # PostgreSQL + Redis (bound to 127.0.0.1)
python manage.py migrate
```

`.env` is git-ignored and holds all secrets. Settings are split into `pulsenotify/settings/{base,local,production}.py`;
`DJANGO_SETTINGS_MODULE` is set in `.env` (`...settings.local`; use `...settings.production` when deploying).

## Run (three terminals, venv active)

```bash
python manage.py runserver                          # 1. API
celery -A pulsenotify worker --loglevel=info        # 2. worker – watch send_notification arrive
celery -A pulsenotify beat --loglevel=info          # 3. beat   – watch check_prices fire every 60s
```

> **Python 3.14:** Celery's default prefork worker pool fails tasks on 3.14, so `settings/local.py` sets
> `CELERY_WORKER_POOL = 'solo'`. Production should set its own pool (or run Python 3.13 or older).

## Admin user

New users always get role `user`. Promote one via PGAdmin (`pulse_userprofile.role = 'admin'`) or:

```bash
python manage.py shell -c "from pulse.models import UserProfile as P; P.objects.filter(user__username='admin_demo').update(role='admin')"
```

## Endpoints

Protected endpoints need the header `Authorization: Bearer <access token>`. Error bodies are JSON; a missing or invalid
token returns `401`.

### POST `/api/auth/register/` (public)

Request:
```json
{ "username": "alice", "password": "securepass", "email": "alice@example.com" }
```
`email` is optional. Any `role` sent is ignored; new users are always `user`. Password minimum length is 8.

`201 Created`:
```json
{ "username": "alice", "access": "eyJ...", "role": "user" }
```
`400` if the username exists or a field is invalid, e.g. `{ "username": ["A user with that username already exists."] }`.

### POST `/api/auth/login/` (public)

Request:
```json
{ "username": "alice", "password": "securepass" }
```
`200 OK`:
```json
{ "username": "alice", "access": "eyJ...", "role": "user" }
```
`401` for bad credentials: `{ "detail": "Invalid credentials." }`.

Both auth endpoints are rate-limited (20 requests/minute); beyond that they return `429`.

### POST `/api/alerts/` (JWT)

The owner is always the token's user; a `user` field in the body is ignored. `origin` and `destination` are upper-cased.

Request:
```json
{ "origin": "DEL", "destination": "BOM", "threshold_price": "4500" }
```
`201 Created`:
```json
{
  "id": 1, "origin": "DEL", "destination": "BOM",
  "threshold_price": "4500.00", "status": "active",
  "created_at": "2026-10-16T11:30:00Z"
}
```
`400` if a field is missing or `threshold_price` is not greater than zero.

### GET `/api/alerts/` (JWT)

No body. Returns only the caller's alerts, newest first. `200 OK` (an empty list if none):
```json
[
  {
    "id": 1, "origin": "DEL", "destination": "BOM",
    "threshold_price": "4500.00", "status": "active",
    "created_at": "2026-10-16T11:30:00Z"
  }
]
```
`status` is `active`, `inactive` or `triggered`.

### DELETE `/api/alerts/<id>/` (JWT)

No body. Deactivates the alert; the row is kept. `200 OK`:
```json
{ "status": "inactive" }
```
`404` if the alert does not exist or belongs to another user (the two cases are indistinguishable by design).

### GET `/api/flights/price/?route=DEL-BOM` (public)

Internal mock price feed called by the `check_prices` task. Known routes: `DEL-BOM`, `BLR-HYD`, `DEL-BLR`, `BOM-GOA`.

`200 OK` (price is a random integer in the route's range):
```json
{ "route": "DEL-BOM", "price": 4200 }
```
`404` for an unknown route: `{ "error": "Route not found" }`.

### GET `/api/admin/summary/` (JWT, admin only)

No body. `200 OK`:
```json
{
  "total_alerts": 24,
  "active_alerts": 18,
  "triggered_alerts": 4,
  "total_notifications": 11,
  "top_routes": [
    { "route": "DEL-BOM", "alert_count": 8 },
    { "route": "BLR-HYD", "alert_count": 6 }
  ]
}
```
`top_routes` lists up to 5 routes. `403` for a non-admin user.

## Tests

```bash
python manage.py test
```

## Postman

Import `PulseNotify.postman_collection.json`. Register the `admin_username` user first (via the register endpoint) and
promote it as above, set `admin_password`, then run the collection. Scenario 13 passes only after Celery has fired at
least one notification (create an alert with a high threshold and wait ~60s).
