"""
Turso database connection and query utilities for Prakrit parser
Uses Turso HTTP API (compatible with Vercel serverless)
"""

import os
import requests
from typing import Dict, List, Optional, Tuple

# Turso database configuration from environment variables
TURSO_DATABASE_URL = os.getenv('TURSO_DATABASE_URL', '')
TURSO_AUTH_TOKEN = os.getenv('TURSO_AUTH_TOKEN', '')


def _to_https_url(url: str) -> str:
    """Convert libsql:// or other URL schemes to https://"""
    if url.startswith('libsql://'):
        return url.replace('libsql://', 'https://', 1)
    if url.startswith('http://'):
        return url.replace('http://', 'https://', 1)
    if not url.startswith('https://'):
        return 'https://' + url
    return url


class TursoDatabase:
    """Turso database connection wrapper using HTTP API"""

    def __init__(self):
        """Initialize Turso database connection"""
        self.connected = False
        self.base_url = _to_https_url(TURSO_DATABASE_URL) if TURSO_DATABASE_URL else ''
        self.pipeline_url = f'{self.base_url}/v2/pipeline' if self.base_url else ''
        self.headers = {
            'Authorization': f'Bearer {TURSO_AUTH_TOKEN}',
            'Content-Type': 'application/json'
        } if TURSO_AUTH_TOKEN else {}

    def _execute(self, sql: str, args: Optional[List] = None) -> Optional[List[List]]:
        """
        Execute a SQL query via Turso HTTP pipeline API

        Args:
            sql: SQL query string
            args: Optional list of query arguments

        Returns:
            List of rows (each row is a list of values), or None on error
        """
        if not self.pipeline_url or not self.headers:
            return None

        stmt = {'sql': sql}
        if args:
            stmt['args'] = [{'type': 'text', 'value': str(a)} for a in args]

        payload = {
            'requests': [
                {'type': 'execute', 'stmt': stmt},
                {'type': 'close'}
            ]
        }

        try:
            resp = requests.post(
                self.pipeline_url,
                headers=self.headers,
                json=payload,
                timeout=8
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            results = data.get('results', [])
            if not results or results[0].get('type') != 'ok':
                return None

            result = results[0].get('response', {}).get('result', {})
            raw_rows = result.get('rows', [])

            # Extract values from typed response
            rows = []
            for raw_row in raw_rows:
                row = []
                for col in raw_row:
                    if isinstance(col, dict):
                        row.append(col.get('value'))
                    else:
                        row.append(col)
                rows.append(row)

            return rows

        except Exception:
            return None

    def connect(self):
        """Establish connection to Turso database"""
        if not self.base_url or not TURSO_AUTH_TOKEN:
            print("Turso: URL or auth token not configured")
            self.connected = False
            return False

        try:
            rows = self._execute("SELECT 1")
            if rows is not None:
                self.connected = True
                print("Turso: Connected successfully")
                return True
            else:
                print("Turso: Connection test failed")
                self.connected = False
                return False
        except Exception as e:
            print(f"Turso: Connection failed: {e}")
            self.connected = False
            return False

    def load_verb_forms(self) -> Dict[str, Dict[str, Dict]]:
        """Load verb forms - returns empty dict (use check_verb_form for on-demand queries)"""
        return {}

    def load_noun_forms(self) -> Dict[str, Dict[str, Dict]]:
        """Load noun forms - returns empty dict (use check_noun_form for on-demand queries)"""
        return {}

    def load_verb_roots(self) -> set:
        """
        Load all verb roots from Turso database

        Returns:
            Set of verb root strings
        """
        if not self.connected:
            if not self.connect():
                return set()

        try:
            rows = self._execute("SELECT DISTINCT root FROM verb_roots")
            if rows is None:
                return set()

            roots = {row[0] for row in rows if row[0]}
            print(f"Turso: Loaded {len(roots)} verb roots")
            return roots
        except Exception:
            return set()

    def load_participle_forms(self) -> Dict[str, Dict[str, Dict]]:
        """Load participle forms - returns empty dict (use check_participle_form for on-demand queries)"""
        return {}

    def get_metadata(self, key: str) -> Optional[str]:
        """
        Get metadata value from database

        Args:
            key: Metadata key

        Returns:
            Metadata value or None
        """
        if not self.connected:
            if not self.connect():
                return None

        try:
            rows = self._execute("SELECT value FROM metadata WHERE key = ?", [key])
            if rows and rows[0]:
                return rows[0][0]
            return None
        except Exception:
            return None

    def check_verb_form(self, form: str) -> List[Tuple[str, Dict]]:
        """
        Check if a verb form exists in the database

        Args:
            form: Verb form to check

        Returns:
            List of (root, grammatical_info) tuples for all matching rows
        """
        if not self.connected:
            if not self.connect():
                return []

        try:
            rows = self._execute("""
                SELECT
                    vr.root,
                    vf.tense,
                    vf.voice,
                    vf.mood,
                    vf.dialect,
                    vf.person,
                    vf.number
                FROM verb_forms vf
                JOIN verb_roots vr ON vf.root_id = vr.root_id
                WHERE vf.form = ?
                LIMIT 50
            """, [form])

            if not rows:
                return []

            results = []
            for row in rows:
                results.append((row[0], {
                    'tense': row[1],
                    'voice': row[2],
                    'mood': row[3],
                    'dialect': row[4],
                    'person': row[5],
                    'number': row[6]
                }))
            return results
        except Exception:
            return []

    def check_noun_form(self, form: str) -> List[Tuple[str, Dict]]:
        """
        Check if a noun form exists in the database

        Args:
            form: Noun form to check

        Returns:
            List of (stem, grammatical_info) tuples for all matching rows
        """
        if not self.connected:
            if not self.connect():
                return []

        try:
            rows = self._execute("""
                SELECT
                    ns.stem,
                    ns.gender,
                    nf.case_name,
                    nf.number
                FROM noun_forms nf
                JOIN noun_stems ns ON nf.stem_id = ns.stem_id
                WHERE nf.form = ?
                LIMIT 50
            """, [form])

            if not rows:
                return []

            results = []
            for row in rows:
                results.append((row[0], {
                    'gender': row[1],
                    'case': row[2],
                    'number': row[3]
                }))
            return results
        except Exception:
            return []

    def check_participle_form(self, form: str) -> List[Tuple[str, Dict]]:
        """
        Check if a participle form exists in the database

        Args:
            form: Participle form to check

        Returns:
            List of (root, grammatical_info) tuples for all matching rows
        """
        if not self.connected:
            if not self.connect():
                return []

        try:
            rows = self._execute("""
                SELECT
                    vr.root,
                    pf.participle_type,
                    pf.suffix,
                    pf.gender,
                    pf.case_name,
                    pf.number
                FROM participle_forms pf
                JOIN verb_roots vr ON pf.root_id = vr.root_id
                WHERE pf.form = ?
                LIMIT 50
            """, [form])

            if not rows:
                return []

            results = []
            for row in rows:
                results.append((row[0], {
                    'participle_type': row[1],
                    'suffix': row[2],
                    'gender': row[3],
                    'case': row[4],
                    'number': row[5]
                }))
            return results
        except Exception:
            return []

    def close(self):
        """Close database connection"""
        self.connected = False
