from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
from pathlib import Path
from datetime import datetime, timezone
import sqlite3, json, uuid, shutil, re, math

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
UPLOADS = ROOT / "uploads"
DB_PATH = ROOT / "lost_found.db"
UPLOADS.mkdir(exist_ok=True)

app = FastAPI(title="Lost & Found AI Prototype", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS items (
          id TEXT PRIMARY KEY,
          report_type TEXT NOT NULL CHECK(report_type IN ('lost','found')),
          item_name TEXT NOT NULL,
          category TEXT,
          colour TEXT,
          shape TEXT,
          location TEXT,
          event_date TEXT,
          time_start TEXT,
          time_end TEXT,
          special_features TEXT NOT NULL DEFAULT '[]',
          feature_recall TEXT NOT NULL DEFAULT 'unknown',
          public_description TEXT,
          private_evidence TEXT,
          image_path TEXT,
          image_analysis_status TEXT NOT NULL DEFAULT 'not_uploaded',
          owner_id TEXT,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS matches (
          id TEXT PRIMARY KEY,
          lost_item_id TEXT NOT NULL REFERENCES items(id),
          found_item_id TEXT NOT NULL REFERENCES items(id),
          score REAL,
          signals TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'candidate',
          created_at TEXT NOT NULL,
          UNIQUE(lost_item_id, found_item_id)
        );
        CREATE TABLE IF NOT EXISTS verifications (
          id TEXT PRIMARY KEY,
          match_id TEXT NOT NULL REFERENCES matches(id),
          status TEXT NOT NULL DEFAULT 'pending',
          evidence_type TEXT,
          notes TEXT,
          reviewer TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """)
init_db()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def row_dict(row):
    if not row:
        return None
    d = dict(row)
    for key in ("special_features",):
        try: d[key] = json.loads(d.get(key) or "[]")
        except Exception: d[key] = []
    # Never return private evidence through normal item endpoints.
    d.pop("private_evidence", None)
    return d

def normalize(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def token_similarity(a, b):
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return None
    if a == b:
        return 1.0
    ta, tb = set(re.findall(r"[a-z0-9]+", a)), set(re.findall(r"[a-z0-9]+", b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)

def date_similarity(a, b):
    if not a or not b:
        return None
    try:
        from datetime import date
        da, db = date.fromisoformat(a), date.fromisoformat(b)
        days = abs((da - db).days)
        return max(0.0, 1.0 - days / 8.0)
    except Exception:
        return None

def time_similarity(a_start, a_end, b_start, b_end):
    # Simple interval overlap for HH:MM values; no timezone conversion needed for same campus.
    if not (a_start and a_end and b_start and b_end):
        return None
    try:
        def mins(s):
            h, m = map(int, s.split(":"))
            return h * 60 + m
        a1, a2, b1, b2 = map(mins, (a_start, a_end, b_start, b_end))
        overlap = max(0, min(a2, b2) - max(a1, b1))
        union = max(a2, b2) - min(a1, b1)
        if union <= 0:
            return 1.0 if a1 == b1 else 0.0
        # Small time-distance allowance for point-ish found time intervals.
        if overlap > 0:
            return overlap / union
        gap = max(b1 - a2, a1 - b2, 0)
        return max(0.0, 1.0 - gap / 180.0)
    except Exception:
        return None

def feature_similarity(lost_features, found_features):
    if not lost_features or not found_features:
        return None
    la = [normalize(x.get("description", "")) for x in lost_features if x.get("description")]
    fb = [normalize(x.get("description", "")) for x in found_features if x.get("description")]
    if not la or not fb:
        return None
    scores = []
    for x in la:
        scores.append(max((token_similarity(x, y) or 0.0 for y in fb), default=0.0))
    return max(scores, default=0.0)

def calculate_score(lost, found):
    # Weights are initial prototype values, not calibrated probabilities.
    weights = {
        "item": 0.10, "colour": 0.10, "shape": 0.10,
        "location": 0.10, "date": 0.10, "time": 0.10,
        "special_features": 0.20, "image": 0.20
    }
    signals = []
    values = {
        "item": token_similarity(lost["item_name"], found["item_name"]),
        "colour": token_similarity(lost["colour"], found["colour"]),
        "shape": token_similarity(lost["shape"], found["shape"]),
        "location": token_similarity(lost["location"], found["location"]),
        "date": date_similarity(lost["event_date"], found["event_date"]),
        "time": time_similarity(lost["time_start"], lost["time_end"], found["time_start"], found["time_end"]),
        "special_features": feature_similarity(
            json.loads(lost["special_features"] or "[]"),
            json.loads(found["special_features"] or "[]")
        ),
        # No image embedding model is installed in this starter. Do not fake image similarity.
        "image": None
    }
    for key, value in values.items():
        if value is not None:
            signals.append({"name": key, "similarity": round(float(value), 3), "weight": weights[key]})
    if not signals:
        return None, []
    denom = sum(s["weight"] for s in signals)
    score = sum(s["similarity"] * s["weight"] for s in signals) / denom if denom else None
    return (round(score * 100, 1) if score is not None else None), signals

def get_item(conn, item_id):
    return conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()

def create_matches_for_item(item_id):
    with connect() as c:
        new_item = get_item(c, item_id)
        if not new_item:
            return
        if new_item["report_type"] == "lost":
            lost_rows = [new_item]
            found_rows = c.execute("SELECT * FROM items WHERE report_type='found' AND status='active'").fetchall()
        else:
            found_rows = [new_item]
            lost_rows = c.execute("SELECT * FROM items WHERE report_type='lost' AND status='active'").fetchall()
        for lost in lost_rows:
            for found in found_rows:
                if lost["status"] != "active" or found["status"] != "active":
                    continue
                # Categories conflict only if both are supplied and differ.
                if lost["category"] and found["category"] and normalize(lost["category"]) != normalize(found["category"]):
                    continue
                score, signals = calculate_score(lost, found)
                if score is None:
                    continue
                mid = str(uuid.uuid4())
                c.execute("""INSERT OR IGNORE INTO matches
                  (id,lost_item_id,found_item_id,score,signals,status,created_at)
                  VALUES(?,?,?,?,?,'candidate',?)""",
                  (mid, lost["id"], found["id"], score, json.dumps(signals), now_iso()))
        c.commit()

@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")

@app.get("/api/health")
def health():
    return {"ok": True, "service": "lost-found-prototype", "image_ai": "not_configured"}

@app.post("/api/items")
async def create_item(
    report_type: str = Form(...),
    item_name: str = Form(...),
    category: str = Form(""),
    colour: str = Form(""),
    shape: str = Form(""),
    location: str = Form(""),
    event_date: str = Form(""),
    time_start: str = Form(""),
    time_end: str = Form(""),
    special_features: str = Form("[]"),
    feature_recall: str = Form("unknown"),
    public_description: str = Form(""),
    private_evidence: str = Form(""),
    owner_id: str = Form(""),
    image: Optional[UploadFile] = File(None)
):
    if report_type not in ("lost", "found"):
        raise HTTPException(422, "report_type must be 'lost' or 'found'")
    if not item_name.strip():
        raise HTTPException(422, "item_name is required")
    # Validate dates on the server; browser-only date limits can be bypassed.
    if event_date.strip():
        try:
            from datetime import date
            parsed_date = date.fromisoformat(event_date.strip())
        except ValueError:
            raise HTTPException(422, "Date must use YYYY-MM-DD format")
        if parsed_date > datetime.now().date():
            raise HTTPException(422, "Date cannot be in the future")
    if time_start.strip() and time_end.strip() and time_end.strip() < time_start.strip():
        raise HTTPException(422, "End time must be after start time")
    # Short-window duplicate protection for accidental repeat clicks/retries.
    # This is a safeguard, not a replacement for authenticated idempotency keys.
    cutoff = (datetime.now(timezone.utc) - __import__("datetime").timedelta(minutes=2)).isoformat()
    with connect() as c:
        duplicate = c.execute("""SELECT * FROM items
            WHERE report_type=? AND LOWER(TRIM(item_name))=LOWER(TRIM(?))
              AND COALESCE(LOWER(TRIM(category)), '')=COALESCE(LOWER(TRIM(?)), '')
              AND COALESCE(LOWER(TRIM(location)), '')=COALESCE(LOWER(TRIM(?)), '')
              AND COALESCE(event_date, '')=? AND COALESCE(time_start, '')=?
              AND COALESCE(time_end, '')=? AND status='active' AND created_at>=?
            ORDER BY created_at DESC LIMIT 1""",
            (report_type, item_name, category.strip() or None, location.strip() or None,
             event_date.strip(), time_start.strip(), time_end.strip(), cutoff)).fetchone()
        if duplicate:
            return {"item": row_dict(duplicate), "message": "This report was just submitted. Returning the existing report to prevent a duplicate."}
    if feature_recall not in ("remembered", "unknown", "none"):
        feature_recall = "unknown"
    try:
        features = json.loads(special_features or "[]")
        if not isinstance(features, list):
            raise ValueError()
        features = [
            {"description": str(x.get("description", "")).strip(),
             "feature_type": str(x.get("feature_type", "other")),
             "source": "owner",
             "owner_confirmed": bool(x.get("owner_confirmed", False)),
             "verification_status": "unverified"}
            for x in features if isinstance(x, dict) and str(x.get("description", "")).strip()
        ]
    except Exception:
        raise HTTPException(422, "special_features must be a JSON array")
    image_path = None
    analysis_status = "not_uploaded"
    if image and image.filename:
        suffix = Path(image.filename).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise HTTPException(415, "Only JPG, PNG, or WEBP images are supported")
        # Basic size cap (8 MB); stream into a temporary file first.
        image.file.seek(0, 2)
        size = image.file.tell()
        image.file.seek(0)
        if size > 8 * 1024 * 1024:
            raise HTTPException(413, "Image must be 8 MB or smaller")
        stored = f"{uuid.uuid4().hex}{suffix}"
        with (UPLOADS / stored).open("wb") as out:
            shutil.copyfileobj(image.file, out)
        image_path = f"/uploads/{stored}"
        analysis_status = "uploaded_analysis_not_configured"
    item_id = str(uuid.uuid4())
    with connect() as c:
        c.execute("""INSERT INTO items
          (id,report_type,item_name,category,colour,shape,location,event_date,time_start,time_end,
           special_features,feature_recall,public_description,private_evidence,image_path,
           image_analysis_status,owner_id,status,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active',?)""",
          (item_id, report_type, item_name.strip(), category.strip() or None, colour.strip() or None,
           shape.strip() or None, location.strip() or None, event_date.strip() or None,
           time_start.strip() or None, time_end.strip() or None, json.dumps(features),
           feature_recall, public_description.strip() or None, private_evidence.strip() or None,
           image_path, analysis_status, owner_id.strip() or None, now_iso()))
        c.commit()
    create_matches_for_item(item_id)
    with connect() as c:
        item = row_dict(get_item(c, item_id))
    return {"item": item, "message": "Report saved. Matching checked against active reports."}

@app.get("/api/items")
def list_items(report_type: Optional[str] = None, status: str = "active"):
    with connect() as c:
        query = "SELECT * FROM items WHERE status=?"
        args = [status]
        if report_type in ("lost", "found"):
            query += " AND report_type=?"
            args.append(report_type)
        query += " ORDER BY created_at DESC"
        rows = c.execute(query, args).fetchall()
        return [row_dict(r) for r in rows]

@app.get("/api/matches")
def list_matches():
    with connect() as c:
        rows = c.execute("""
          SELECT m.*, l.item_name AS lost_name, l.location AS lost_location,
                 l.image_path AS lost_image, f.item_name AS found_name,
                 f.location AS found_location, f.image_path AS found_image
          FROM matches m JOIN items l ON l.id=m.lost_item_id
          JOIN items f ON f.id=m.found_item_id
          WHERE l.status='active' AND f.status='active'
          ORDER BY m.score DESC, m.created_at DESC
        """).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["signals"] = json.loads(d["signals"] or "[]")
            results.append(d)
        return results

@app.post("/api/matches/{match_id}/request-verification")
def request_verification(match_id: str):
    with connect() as c:
        m = c.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        if not m:
            raise HTTPException(404, "Match not found")
        existing = c.execute("SELECT * FROM verifications WHERE match_id=?", (match_id,)).fetchone()
        if existing:
            return dict(existing)
        vid = str(uuid.uuid4())
        t = now_iso()
        c.execute("""INSERT INTO verifications
          (id,match_id,status,evidence_type,notes,reviewer,created_at,updated_at)
          VALUES(?,?,'pending',NULL,NULL,NULL,?,?)""", (vid, match_id, t, t))
        c.execute("UPDATE matches SET status='verification_pending' WHERE id=?", (match_id,))
        c.commit()
        return {"id": vid, "match_id": match_id, "status": "pending",
                "message": "Verification started. No item has been authorized for return."}

class VerificationDecision(BaseModel):
    status: str
    evidence_type: Optional[str] = None
    notes: Optional[str] = None
    reviewer: Optional[str] = None

@app.post("/api/verifications/{verification_id}/decision")
def verification_decision(verification_id: str, decision: VerificationDecision):
    if decision.status not in ("verified", "rejected", "needs_review"):
        raise HTTPException(422, "status must be verified, rejected, or needs_review")
    # Prototype endpoint only: production must require authenticated staff authorization.
    with connect() as c:
        v = c.execute("SELECT * FROM verifications WHERE id=?", (verification_id,)).fetchone()
        if not v:
            raise HTTPException(404, "Verification not found")
        t = now_iso()
        c.execute("""UPDATE verifications SET status=?, evidence_type=?, notes=?, reviewer=?, updated_at=?
                     WHERE id=?""",
                  (decision.status, decision.evidence_type, decision.notes, decision.reviewer, t, verification_id))
        m = c.execute("SELECT * FROM matches WHERE id=?", (v["match_id"],)).fetchone()
        if decision.status == "verified":
            c.execute("UPDATE matches SET status='verified' WHERE id=?", (v["match_id"],))
            c.execute("UPDATE items SET status='resolved' WHERE id IN (?,?)",
                      (m["lost_item_id"], m["found_item_id"]))
        elif decision.status == "rejected":
            c.execute("UPDATE matches SET status='rejected' WHERE id=?", (v["match_id"],))
        else:
            c.execute("UPDATE matches SET status='needs_review' WHERE id=?", (v["match_id"],))
        c.commit()
        return {"verification_id": verification_id, "status": decision.status,
                "match_status": "verified" if decision.status == "verified" else decision.status,
                "message": "Prototype decision saved. Production requires authenticated reviewer permissions."}

@app.post("/api/recheck")
def recheck_matches():
    # Useful after importing records or changing scoring logic.
    with connect() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM items WHERE status='active'").fetchall()]
    for item_id in ids:
        create_matches_for_item(item_id)
    return {"checked_active_reports": len(ids), "message": "Reconciliation complete."}
