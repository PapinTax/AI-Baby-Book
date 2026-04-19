# AI Baby Book

Scan your photo library and discover childhood milestones — first smile, first steps, first birthday — automatically organized into a beautiful timeline, powered by Claude Vision.

## Architecture

```
backend/   FastAPI + SQLAlchemy (SQLite) + Claude Vision API
frontend/  Next.js 14 + Tailwind CSS
```

## Quick Start

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env

uvicorn main:app --reload
# API running at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
# UI running at http://localhost:3000
```

### 3. Run backend tests

```bash
cd backend
pytest
```

## How It Works

1. **Import** — Enter a local folder path in the UI. The backend walks the directory, reads EXIF timestamps, and generates thumbnails.
2. **Detect** — Each photo is sent to Claude Vision (Haiku by default) with a structured milestone taxonomy prompt. Claude returns JSON with milestone type, confidence, description, and visual evidence.
3. **Review** — You see each detection with confidence score. Approve or reject before anything enters your timeline.
4. **Timeline** — Approved milestones render in chronological order grouped by year.
5. **Export** — Download a PDF keepsake book with one click.

## Milestone Types Detected

| Type | Description |
|---|---|
| `first_smile` | Earliest captured smile |
| `first_crawl` | Crawling on hands and knees |
| `first_steps` | First independent steps |
| `first_walk` | Confident walking |
| `first_solid_food` | Eating solid food in high chair |
| `first_birthday` | First birthday with cake |
| `vacation` | Travel / landmark moments |
| `holiday` | Holiday scenes |
| `memorable_moment` | Other special family moments |
| ...and more | See `models.py` for full list |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | required | Your Anthropic API key |
| `DATABASE_URL` | `sqlite+aiosqlite:///./baby_book.db` | SQLAlchemy async DB URL |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend URL for frontend |

## Cost Estimate

Claude Haiku vision pricing (as of 2025): ~$0.0004 per image. A 500-photo library costs roughly **$0.20** to scan.

Use `model=claude-sonnet-4-6` for a second-pass accuracy boost on borderline detections.

## Privacy

- Photos are read from your local filesystem by the backend process.
- Base64-encoded images are sent to the Anthropic API for milestone detection. No other third-party services receive your photos.
- Results are stored in a local SQLite database (`baby_book.db`).
- Nothing is persisted in any cloud storage.
