# AI Baby Book — Claude Context

## Project overview
Web app that scans a local photo/video library, detects childhood milestones using
Claude Vision API, lets the user review and approve detections, then renders them
in a chronological timeline and exports a PDF keepsake book.

**Owner:** Christopher LaGrutta  
**Children:**
- **Claire** — born 2024-01-30
- **Luciana** — born 2025-09-10

**Dev branch:** `claude/milestone-photo-detector-UZQgf`  
**Stack:** FastAPI + SQLAlchemy/aiosqlite (SQLite) · Next.js 14 + Tailwind CSS  
**Started on:** Windows 11. Backend runs in a Linux container (WSL or similar).
Windows filesystem is NOT accessible from the backend shell — use `python3` and
relative paths for any file checks.

---

## Quick start (Windows)

Double-click **`start.bat`** in the project root. It:
1. Checks `backend/.env` exists (needs `ANTHROPIC_API_KEY=sk-ant-...`)
2. Opens a terminal running `uvicorn main:app --reload --port 8000`
3. Opens a terminal running `npm run dev` (frontend on port 3000)
4. Opens browser to `http://localhost:3000` after 8 seconds

Manual start if needed:
```
# backend
cd backend && python -m uvicorn main:app --reload --port 8000

# frontend
cd frontend && npm run dev
```

After changing Python files, uvicorn auto-reloads. After changing frontend files,
Next.js hot-reloads. **Always hard-refresh the browser (Ctrl+Shift+R) after
frontend changes** — the browser may cache old JS.

---

## File structure

```
AI-Baby-Book/
├── start.bat                        # one-click Windows launcher
├── backend/
│   ├── main.py                      # FastAPI app, router mounts, CORS, static /thumbnails
│   ├── database.py                  # SQLAlchemy async engine + SessionLocal
│   ├── models.py                    # ORM: Photo, Milestone, Child
│   ├── requirements.txt
│   ├── .env                         # ANTHROPIC_API_KEY (not in git)
│   ├── routers/
│   │   ├── photos.py                # scan + upload endpoints, _run_scan pipeline
│   │   ├── milestones.py            # review, approve, deduplicate endpoints
│   │   ├── timeline.py              # timeline + PDF export
│   │   └── children.py              # CRUD for Child records
│   └── services/
│       ├── photo_scanner.py         # file enumeration, EXIF/video date, thumbnail gen
│       ├── milestone_detector.py    # Claude API calls (prefilter + detect)
│       ├── face_detector.py         # local Haar-cascade face detection (free pre-filter)
│       └── timeline.py              # timeline query helpers
└── frontend/
    ├── src/app/
    │   ├── page.tsx                 # home / onboarding
    │   ├── upload/page.tsx          # scan + single-upload UI
    │   ├── milestones/page.tsx      # review queue + approved tab
    │   ├── timeline/page.tsx        # chronological timeline
    │   └── settings/page.tsx        # children management
    ├── src/components/
    │   ├── MilestoneCard.tsx        # review + approved card (child reassign, label edit)
    │   ├── ConfidenceBadge.tsx
    │   └── Lightbox.tsx
    ├── src/lib/api.ts               # all API calls
    └── src/hooks/useReviewKeyboard.ts
```

---

## Scan pipeline (`routers/photos.py` → `_run_scan`)

Phases in order — each sets `job["status"]` explicitly before its loop:

| Status key | UI label | What happens |
|---|---|---|
| `listing` | Finding photos… | `list_photo_files()` — rglob + skip iCloud placeholders |
| *(none)* | — | DB cache filter: skip `(file_path, file_size)` already in DB |
| `date_checking` | Step 1/5 | Parallel EXIF/video date read; drop outside date range |
| `scanning` | Step 2/5 | Parallel thumbnail generation (`include_full=False`) |
| `face_check` | Step 3/5 | Local Haar-cascade; drop photos with no detected face |
| `prefiltering` | Step 4/5 | Claude Haiku yes/no "does this contain a child?" |
| `detecting` | Step 5/5 | Claude Sonnet/Haiku full milestone detection; lazily hydrates `full_b64` |
| `saving` | Saving… | Upsert Photo rows, insert Milestone rows with child_id + computed age |
| `complete` | Scan complete! | — |

Progress streams via SSE at `/photos/scan/{session_id}/stream`.

**Key concurrency env vars** (set in `backend/.env` to tune for the machine):
```
SCAN_CONCURRENCY=8   # local file I/O + CPU (EXIF reads, thumbnail gen, face detect)
API_CONCURRENCY=8    # Claude API calls (prefilter + detect)
FACE_CONCURRENCY=4   # OpenCV face detection threads
```

---

## Photo/video support

**Images:** `.jpg .jpeg .png .heic .heif .tiff .tif .webp`  
**Videos:** `.mov .mp4 .m4v .avi .mkv .3gp`

For videos, `scan_video()` samples 5 evenly-spaced frames, picks the sharpest
(Laplacian variance), and returns it as a `PhotoScanResult`. Date is read from
QuickTime/MP4 `creation_time` via `ffprobe` if available, otherwise falls back to
file `mtime`.

**iCloud on Windows:** Uses `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` (0x00400000)
via `ctypes` to detect placeholder files that haven't been downloaded yet. These
are skipped entirely — no download is triggered.

---

## iCloud Photos folder structure (user's machine)

```
C:\Users\ChristopherLaGrutta\Pictures\iCloud Photos\Photos\
```

All photos are in one flat `Photos\` folder — **no year/month subfolders**.
iPhone album structure is NOT mirrored on Windows. Shared Albums would appear
under `Shared\` but the user has not set those up.

**Recommended scan workflow:**
1. Import page → "Scan for child" dropdown → select **Claire**
   - Start date auto-fills to `2024-01-30`, set end date to `2025-09-09`
   - Directory: `C:\Users\ChristopherLaGrutta\Pictures\iCloud Photos\Photos`
2. After Claire's scan completes, select **Luciana**
   - Start date auto-fills to `2025-09-10`
   - Same directory
   - DB cache skips all pre-2025-09-10 files that were already scanned

---

## Per-child scan mode

`ScanRequest.child_id` (optional int):
- When set, every Milestone saved in that scan gets `child_id` pre-assigned
- `approximate_age` is computed exactly: `photo.taken_at - child.birth_date`
- No manual assignment needed in the review queue

---

## Milestone review

**Pending tab:**
- Child dropdown sets the child *before* clicking Approve (decoupled)
- Approve button shows "Approve for Claire" if a child is selected
- Keyboard shortcuts: `j`/`k` navigate, `a` approve, `r` reject

**Approved tab:**
- Child dropdown is always visible — change it to reassign; saves immediately
- Age recomputes on the server when child changes
- **"Remove duplicates"** button → `POST /milestones/deduplicate`
  - Keeps only the earliest photo per `(child_id, milestone_type)` for
    once-per-child types (first_smile, first_steps, etc.)
  - Does NOT deduplicate: birthday, vacation, holiday, memorable_moment

---

## Age computation

Exact formula (no AI estimation):
```python
delta_days = (photo.taken_at.date() - child.birth_date).days
years, rem = divmod(delta_days, 365)
months = rem // 30
# → "3 months", "1 year", "1 year, 2 months", "newborn"
```

Runs:
1. At scan save time (when `child_id` is provided in ScanRequest)
2. On `PATCH /milestones/{id}` whenever `child_id` is set/changed

---

## Key API endpoints

```
POST /photos/scan                    start background scan
GET  /photos/scan/{id}/stream        SSE progress stream
POST /photos/upload                  single photo/video upload + detect
GET  /photos                         list all imported photos

GET  /milestones/pending             review queue
PATCH /milestones/{id}               approve/reject, reassign child, edit label
POST /milestones/deduplicate         remove duplicates (keep earliest per child+type)
POST /milestones/rescan              re-run Sonnet on low-confidence pending items
DELETE /milestones/{id}

GET  /timeline                       approved milestones chronological
GET  /timeline/stats
GET  /timeline/export/pdf            single-child PDF
GET  /timeline/export/pdf/full       all-children PDF

GET  /children
POST /children
PATCH /children/{id}
```

---

## Database models (`models.py`)

**Photo:** `id, file_path (unique), filename, taken_at, file_size, width, height, thumbnail_path, processed, scan_session_id`

**Milestone:** `id, photo_id, child_id (nullable), milestone_type, label, description, confidence, approximate_age, approved (null=pending/true/false), evidence (JSON)`

**Child:** `id, name, birth_date`

SQLite file: `backend/baby_book.db`  
Thumbnails: `backend/thumbnails/` (served statically at `/thumbnails/`)

---

## Dependencies of note

```
pillow>=11.0.0          image open/resize/JPEG encode
pillow-heif>=0.18.0     HEIC/HEIF support (iPhone photos)
opencv-python-headless  Haar-cascade face detection + video frame extraction
numpy>=1.26.0           required by OpenCV
anthropic==0.39.0       Claude API client
ffprobe (optional)      video creation_time metadata; falls back to mtime if absent
```

---

## Known issues / things to watch

- **Browser cache:** After any frontend change, press **Ctrl+Shift+R** in the browser
  to force a hard reload — the Next.js dev server hot-patches JS but the browser
  may serve stale files.
- **uvicorn --reload wipes in-memory scan jobs:** If a scan is running and a `.py`
  file changes (triggering reload), `_scan_jobs` dict is cleared and the scan dies.
  Don't save Python files mid-scan.
- **SQLite 999-parameter limit:** `_already_processed_keys()` chunks IN clauses
  to 500 paths. Don't remove that chunking.
- **ffprobe not installed:** Video date falls back to file `mtime` silently. This
  is fine for iPhone videos where mtime is usually accurate.
- **iCloud placeholder detection is Windows-only:** `_is_cloud_placeholder()` uses
  `ctypes.windll` — it returns `False` on non-Windows and all files are processed.

---

## Recent changes (this session)

1. Fixed phase-transition loop in scan progress (status now set explicitly per phase)
2. Speed optimisations: parallel I/O (asyncio.Semaphore), DB cache skip, lazy
   `full_b64`, local Haar-cascade face pre-filter
3. Video support: MOV/MP4/M4V/AVI/MKV/3GP via OpenCV frame extraction
4. Child reassignment on approved milestones (live dropdown, saves immediately)
5. Exact age computation from birth_date (replaces Claude's visual estimate)
6. Duplicate milestone removal (`/milestones/deduplicate`)
7. Per-child scan mode: select child → date range auto-fills → milestones
   auto-assigned with exact ages
