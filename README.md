# Parser4Prakrit

A web-based parser and analyzer for the Prakrit language. Analyzes verb forms, noun forms, and participles with grammatical breakdown including tense, person, number, case, gender, and Sanskrit terminology.

**Database:** Turso (LibSQL) | **Framework:** Flask | **Deployment:** Vercel

## Features

- Analyze Prakrit verb forms (present, past, future tense)
- Analyze noun declensions (8 cases, 3 genders, singular/plural)
- Participle analysis (absolutive, present, past passive)
- Devanagari and Harvard-Kyoto (HK) transliteration support
- Confidence scoring with multiple possible analyses
- On-demand database queries to Turso (5M+ verb forms, 6400+ roots)
- Fallback to local JSON data when database is unavailable

---

## Local Development Setup

### 1. Clone the repository

```bash
git clone https://github.com/svyoma/parser4prakrit.git
cd parser4prakrit
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your Turso credentials:

```
TURSO_DATABASE_URL=libsql://your-database.turso.io
TURSO_AUTH_TOKEN=your-token-here
```

The parser works without these (falls back to local JSON), but database access provides much better results.

### 4. Run locally

```bash
python unified_parser.py
```

The app starts at `http://localhost:5000`.

### CLI mode

Analyze a word directly from the terminal:

```bash
python unified_parser.py karedi
```

---

## Deploy to Vercel

### Step 1: Push to GitHub

Your `.env` file is in `.gitignore` and will NOT be pushed. This is correct.

```bash
git add .
git commit -m "Initial commit"
git push origin main
```

### Step 2: Import to Vercel

1. Go to [vercel.com](https://vercel.com) and click **"New Project"**
2. Import your GitHub repository
3. Vercel auto-detects the Python project via `vercel.json`

### Step 3: Configure Environment Variables in Vercel Dashboard

**This is the critical step.** In your Vercel project:

1. Go to **Settings** > **Environment Variables**
2. Add these variables:

| Name | Value | Environment |
|------|-------|-------------|
| `TURSO_DATABASE_URL` | `libsql://your-database.turso.io` | Production, Preview, Development |
| `TURSO_AUTH_TOKEN` | `your-turso-jwt-token` | Production, Preview, Development |

3. Click **Save**, then **Redeploy**

### How the flow works

```
GitHub repo (public, NO secrets in code)
         |
         v
Vercel clones repo on every git push
         |
         v
Vercel injects env vars at runtime (stored in Vercel dashboard)
         |
         v
App calls os.getenv('TURSO_AUTH_TOKEN') - gets the value from Vercel
         |
         v
App queries Turso database via HTTP API
```

Your secrets never appear in GitHub. Vercel stores them encrypted and provides them to your serverless functions at runtime.

---

## API Endpoints

### `POST /api/parse`

Analyze any Prakrit word (verb, noun, or participle).

**Request:**
```json
{ "form": "karedi" }
```

**Response:**
```json
{
  "success": true,
  "original_form": "karedi",
  "hk_form": "karedi",
  "data_source": "turso",
  "analyses": [
    {
      "form": "karedi",
      "root": "kar",
      "type": "verb",
      "source": "attested_form",
      "confidence": 1.0,
      "tense": "present",
      "voice": "active",
      "person": "third_singular",
      "number": "singular",
      "dialect": "shauraseni"
    }
  ],
  "total_found": 33
}
```

### `POST /api/analyze`

Legacy endpoint. Accepts `verb_form` parameter.

### `POST /api/feedback`

Submit user feedback on analysis correctness.

### `GET /`

Web UI for interactive analysis.

---

## Database

The parser uses a **Turso** (LibSQL) database containing:

- **6,439 verb roots** from classical Prakrit texts
- **5,144,830 verb forms** with full grammatical annotations
- **Noun stems and forms** with case/gender/number
- **Participle forms** with type classification

The database is **read-only**. Queries are made on-demand via Turso's HTTP API, compatible with Vercel's serverless architecture.

### For contributors

The database credentials are not in the repository. Options:

1. Ask the maintainer for read-only credentials
2. The parser works without database access by falling back to local JSON files (`verbs1.json`)

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `TURSO_DATABASE_URL` | For DB access | Turso database URL (`libsql://name.turso.io`) |
| `TURSO_AUTH_TOKEN` | For DB access | Turso JWT authentication token |
| `FLASK_ENV` | No | `development` or `production` (default on Vercel) |
| `PORT` | No | Server port for local dev (default: `5000`) |

---

## Project Structure

```
parser4prakrit/
├── unified_parser.py          # Main Flask app + parser (Vercel entry point)
├── turso_db.py                # Turso HTTP API database client
├── verb_analyzer.py           # Verb analysis engine
├── noun_analyzer.py           # Noun analysis engine
├── devanagari_transliterator.py
├── dictionary_lookup.py
├── input_validation.py
├── templates/
│   └── unified_analyzer.html  # Web UI
├── static/
│   ├── styles.css
│   └── verb-analyzer.js
├── verbs1.json                # Verb roots (local fallback data)
├── vercel.json                # Vercel deployment config
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variable template
└── LICENSE
```

---

## Testing

```bash
# Run all tests
python -m pytest test_*.py -v

# Test a specific word via CLI
python unified_parser.py karedi

# Test database connection
python -c "from turso_db import TursoDatabase; db = TursoDatabase(); print(db.connect())"
```

---

## License

MIT License - Copyright (c) 2025 svyoma

## Credits

Created by [svyoma](https://svyoma.github.io/about)

## References

- Pischel, Richard. *Grammatik der Prakrit-Sprachen*. 1900.
- Woolner, Alfred C. *Introduction to Prakrit*. 1928.
- Tagare, G.V. *Historical Grammar of Apabhramsha*. 1948.
