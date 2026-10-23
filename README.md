# Findly — Lost & Found AI Prototype

A runnable starter app with a responsive HTML/CSS/JavaScript frontend and a FastAPI + SQLite backend.

## Included
- Report lost and found items
- Photo upload (JPG, PNG, WEBP; max 8 MB)
- Optional details and optional distinctive features
- Private verification clue stored in the database and excluded from normal item-list responses
- Weighted matching using available text attributes, location, date/time and described special features
- New lost/found reports trigger comparison against active reports
- Active reports remain searchable until resolved
- Candidate matches, verification request, and reviewer decision workflow
- Manual recheck endpoint for existing reports

## Not included yet
- Real image recognition or image embeddings. The app stores photos but explicitly marks image analysis as not configured. It does not fabricate image-similarity percentages.
- Production authentication, authorization, email/SMS notifications, rate limiting, malware scanning, cloud storage, or a formal audit log.
- The reviewer decision endpoint is for local demonstration only. Do not deploy it publicly as-is.

## Requirements
- Python 3.10+
- pip

## Deploy publicly on Render (demo only)
1. Create a GitHub repository and upload the contents of this folder (including `render.yaml`).
2. In Render, choose **New → Web Service**, connect that repository, and create the service. Render can use the settings in `render.yaml`.
3. After the deploy succeeds, open the public `https://...onrender.com` URL shown in the Render dashboard.

**Important:** This is a demonstration prototype, not safe for public production use. It lacks authentication and authorization, and its local SQLite database and uploaded images may not persist on a free host across redeploys/restarts. Do not submit sensitive ownership evidence or personal information. Configure persistent storage/database and access controls before real use.

## Run on Windows (VS Code terminal)
1. Extract the ZIP.
2. Open the `lost_found_ai_prototype` folder in VS Code.
3. Open Terminal → New Terminal.
4. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, use Command Prompt:
   ```bat
   .venv\Scripts\activate.bat
   ```

5. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

6. Start the server:

   ```powershell
   uvicorn app:app --reload
   ```

7. Open:
   - UI: http://127.0.0.1:8000
   - Interactive API docs: http://127.0.0.1:8000/docs
   - Health: http://127.0.0.1:8000/api/health

## Test the main workflow
1. Submit a lost report, e.g. headphones, category Electronics, colour black, location College Library, date/time and optional scratch description.
2. Submit a found report with similar information.
3. Open Possible matches. The app should create a candidate automatically.
4. Select Verify ownership, enter evidence type and reviewer.
5. Confirm verification only if the evidence is sufficient. Otherwise choose the follow-up review option.
6. Check Active reports; verified linked reports are no longer active.

## API endpoints
- `GET /api/health`
- `POST /api/items` (multipart form; optional `image`)
- `GET /api/items?report_type=lost|found&status=active`
- `GET /api/matches`
- `POST /api/matches/{match_id}/request-verification`
- `POST /api/verifications/{verification_id}/decision`
- `POST /api/recheck`

## Matching notes
The current weights are starter values, not trained or calibrated. A match score is a ranking score, not a probability of ownership. The image weight is excluded because no image-embedding model is connected. The score is normalized across signals with available values.

## Production hardening before real deployment
- Add authenticated accounts and role-based access (owner, finder, reviewer/admin).
- Restrict verification decisions to authorized staff.
- Add consent, retention/deletion rules and audit logging.
- Validate file content, not only filename extension; scan uploads and store outside the public web root.
- Use private object storage and signed URLs for images.
- Add CSRF protections if using cookie authentication, rate limits and abuse reporting.
- Integrate a real image embedding model and evaluate false-positive/false-negative rates with labelled data.
- Avoid showing private evidence in public listings or match cards.
