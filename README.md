# Parser4Prakrit

A morphological parser and analyzer for the Prakrit language. Given a Prakrit word, it identifies the root, grammatical form, and provides a detailed breakdown including tense, person, number, case, gender, voice, and dialect — with corresponding Sanskrit grammatical terminology (e.g., *prathamA-vibhakti*, *vartamAna-kAla*).

Supports verb forms, noun declensions, and participles across major Prakrit dialects including Shauraseni, Maharashtri, and Magadhi.

## Overview

Prakrit refers to a group of Middle Indo-Aryan languages historically used in literature, drama, and philosophical texts. Parsing Prakrit is challenging due to its complex morphology and dialectal variation. This tool provides computational analysis by matching input forms against a database of over 5 million attested verb forms and applying rule-based suffix analysis for unattested forms.

### How it works

1. **Attested form lookup** — The input is checked against a database of 5.1M+ verb forms and noun forms with full grammatical annotations.
2. **Ending-based analysis** — If no exact match is found, suffix rules derived from Prakrit grammars are applied against 6,400+ verb roots to generate possible analyses.
3. **Confidence scoring** — Each analysis is assigned a confidence score. Attested forms get the highest confidence; suffix-based guesses are ranked by specificity.

### What it analyzes

| Category | Details |
|----------|---------|
| **Verbs** | Present, past, future tense; active/passive voice; imperative/optative mood; all persons and numbers |
| **Nouns** | 8 cases (*vibhakti*), 3 genders, singular/plural |
| **Participles** | Absolutive, present participle, past passive participle |
| **Transliteration** | Input in Devanagari is automatically converted to Harvard-Kyoto (HK) for processing |

## Live Demo

Deployed on Vercel: [parser4prakrit.vercel.app](https://parser4prakrit.vercel.app)

## Quick Start

```bash
git clone https://github.com/svyoma/parser4prakrit.git
cd parser4prakrit
pip install -r requirements.txt
python unified_parser.py
```

Open `http://localhost:5000` for the web interface.

### CLI usage

```bash
python unified_parser.py karedi
```

## API

### `POST /api/parse`

```json
{ "form": "karedi" }
```

Returns:

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
      "dialect": "shauraseni",
      "sanskrit_terms": {
        "tense": "vartamAna-kAla",
        "voice": "kartari-prayoga",
        "number": "eka-vacana",
        "person": "prathama-puruSa"
      }
    }
  ],
  "total_found": 33
}
```

### Other endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web interface |
| `/api/analyze` | POST | Legacy endpoint (accepts `verb_form`) |
| `/api/feedback` | POST | Submit feedback on analysis correctness |

## Database

The parser queries a [Turso](https://turso.tech) (LibSQL) database containing:

- **6,439 verb roots** from classical Prakrit texts
- **5,144,830 verb forms** with grammatical annotations
- **Noun stems and forms** with case, gender, and number
- **Participle forms** with type classification

Queries are made on-demand via Turso's HTTP API. When the database is unavailable, the parser falls back to local JSON data (`verbs1.json`).

## Project Structure

```
parser4prakrit/
├── unified_parser.py             # Flask app, parser engine, Vercel entry point
├── turso_db.py                   # Turso HTTP API client
├── devanagari_transliterator.py  # Devanagari ↔ HK transliteration
├── dictionary_lookup.py          # Dictionary lookup utilities
├── verbs1.json                   # Verb roots (local fallback)
├── templates/
│   └── unified_analyzer.html     # Web UI
├── static/
│   ├── styles.css
│   └── verb-analyzer.js
├── vercel.json                   # Vercel deployment config
├── requirements.txt
└── .env.example                  # Environment variable template
```

## Contributing

Contributions are welcome. To run locally with full database access, copy `.env.example` to `.env` and contact the maintainer for read-only Turso credentials. The parser works without database access (falls back to local JSON), but results are limited.

```bash
cp .env.example .env
# Edit .env with your credentials
python unified_parser.py
```

## References

- Pischel, Richard. *Grammatik der Prakrit-Sprachen*. 1900.
- Woolner, Alfred C. *Introduction to Prakrit*. 1928.
- Tagare, G.V. *Historical Grammar of Apabhramsha*. 1948.

## License

MIT License — see [LICENSE](LICENSE) for details.

---

Created by [svyoma](https://svyoma.github.io/about)
