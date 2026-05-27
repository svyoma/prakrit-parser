"""
Unified Prakrit Parser
Combines verb and noun analysis with holistic ending-based guessing
Implements proper suffix priority and blocking rules
"""

import re
import json
import os
from typing import Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load .env file for local development (ignored on Vercel where env vars are set in dashboard)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Sanskrit Terminology Mappings
SANSKRIT_TERMS = {
    # Participle types (kRdanta)
    'absolutive': 'sambandhaka-kRdanta',           # "having done" — pUrvakAlika-kRdanta
    'infinitive': 'kriyArthaka-kRdanta',            # Sanskrit-model "-tuM" ("to do")
    'hetvartha': 'hetvartha-kRdanta',               # Jain Prakrit-native "-iuM/euM/uM" purpose form
    'present_participle': 'vartamAna-kRdanta',
    'past_passive_participle': 'bhUta-kRdanta',
    'future_passive_participle': 'kRtya-kRdanta',  # gerundive ("to be done")

    # Case names (vibhakti)
    'nominative': 'prathamA-vibhakti',
    'accusative': 'dvitIyA-vibhakti',
    'instrumental': 'tRtIyA-vibhakti',
    'dative': 'caturthI-vibhakti',
    'ablative': 'paJcamI-vibhakti',
    'genitive': 'SaSThI-vibhakti',
    'locative': 'saptamI-vibhakti',
    'vocative': 'saMbodhana',

    # Tense/mood
    'present': 'vartamAna-kAla',
    'past': 'bhUta-kAla',
    'future': 'bhaviSya-kAla',
    'imperative': 'AjJA-artha',
    'optative': 'vidhiliG',

    # Voice
    'active': 'kartari-prayoga',
    'passive': 'karmaNi-prayoga',

    # Number
    'singular': 'eka-vacana',
    'plural': 'bahu-vacana',
    'dual': 'dvi-vacana',

    # Gender
    'masculine': 'puMliGga',
    'feminine': 'strI-liGga',
    'neuter': 'napuMsaka-liGga',

    # Person
    'first': 'uttama-puruSa',
    'second': 'madhyama-puruSa',
    'third': 'prathama-puruSa',
}

# Ending type descriptions for nouns
NOUN_ENDING_TYPES = {
    'a': 'a-ending (akArAnta)',
    'A': 'A-ending (AkArAnta)',
    'i': 'i-ending (ikArAnta)',
    'I': 'I-ending (IkArAnta)',
    'u': 'u-ending (ukArAnta)',
    'U': 'U-ending (UkArAnta)',
}

# Optional dependencies
try:
    from flask import Flask, render_template, request, jsonify
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False

try:
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=SyntaxWarning)
        from aksharamukha import transliterate as aksh_transliterate
    HAS_AKSHARAMUKHA = True
except ImportError:
    HAS_AKSHARAMUKHA = False

# Initialize Flask app only if available
if HAS_FLASK:
    app = Flask(__name__)

class PrakritUnifiedParser:
    """
    Unified parser for both Prakrit verbs and nouns with intelligent ending-based analysis
    """

    def __init__(self, auto_download=True):
        """
        Initialize parser

        Args:
            auto_download: If True, automatically download missing databases
        """
        # Auto-download databases if missing
        if auto_download:
            self.ensure_databases()

        self.load_data()
        self.load_feedback_data()
        self.initialize_suffix_database()
        self.load_dictionary()

    def ensure_databases(self):
        """Legacy method - databases now loaded from Turso"""
        # No longer needed - Turso is the primary data source
        # Local SQLite files only used as fallback
        pass

    def load_dictionary(self):
        """Load dictionary database if available"""
        self.dictionary = None
        try:
            dict_path = os.path.join(os.path.dirname(__file__), 'prakrit-dict.db')
            if os.path.exists(dict_path):
                from dictionary_lookup import PrakritDictionary
                self.dictionary = PrakritDictionary(dict_path)
                print("✓ Dictionary database loaded")
        except Exception as e:
            # Dictionary is optional
            pass

    def load_data(self):
        """Load verb and noun data from Turso database, with fallbacks"""
        # Initialize Turso database connection
        self.turso_db = None
        self.data_source = "none"  # Track which source is actually used

        try:
            from turso_db import TursoDatabase
            self.turso_db = TursoDatabase()
            if self.turso_db.connect():
                # Turso connected - use on-demand queries via check_verb_form/check_noun_form
                # Only load verb_roots (small set needed for ending-based analysis)
                self.verb_roots = self.turso_db.load_verb_roots()
                if not self.verb_roots:
                    # Fallback: load verb roots from local JSON
                    self.verb_roots = self.load_verb_roots()
                self.all_verb_forms = {}  # On-demand via check_attested_verb_form
                self.all_noun_forms = {}  # On-demand via check_attested_noun_form
                self.all_participle_forms = {}  # On-demand via check_participle_form
                self.data_source = "turso"
                print(f"Data source: Turso (on-demand queries, {len(self.verb_roots)} verb roots loaded)")
                return
        except Exception as e:
            print(f"Turso not available, using local fallback: {e}")

        # Fallback to local files
        self.verb_roots = self.load_verb_roots()
        self.all_verb_forms = self.load_verb_forms_db()
        self.all_noun_forms = self.load_noun_forms_db()
        self.all_participle_forms = {}  # No local participle data yet

        # Determine which fallback source worked
        if self.verb_roots:
            self.data_source = "local_json"
            print(f"Data source: Local JSON (verb_roots: {len(self.verb_roots)}, verb_forms: {len(self.all_verb_forms)}, noun_forms: {len(self.all_noun_forms)})")

    def load_verb_roots(self):
        """Load verb roots from verbs1.json and filter out invalid single-letter consonants"""
        try:
            verbs1_path = os.path.join(os.path.dirname(__file__), 'verbs1.json')
            with open(verbs1_path, encoding='utf-8') as f:
                verbs1_data = json.load(f)
                roots = set(verbs1_data.values())

                # Filter out single-letter consonants (they can't be valid Prakrit roots)
                # Only single-letter vowels are valid (A, I, U, a, i, u, e, o)
                valid_single_letters = {'A', 'I', 'U', 'a', 'i', 'u', 'e', 'o', 'ā', 'ī', 'ū'}
                filtered_roots = set()
                for root in roots:
                    if len(root) == 1 and root not in valid_single_letters:
                        # Skip single-letter consonants like N, d, g, etc.
                        continue
                    filtered_roots.add(root)

                return filtered_roots
        except Exception as e:
            print(f"Warning: Could not load verbs1.json: {e}")
            return set()

    def load_verb_forms_db(self):
        """Load verb forms from SQLite database or JSON fallback"""
        # Try SQLite database first
        try:
            import sqlite3
            db_path = os.path.join(os.path.dirname(__file__), 'verb_forms.db')
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()

                # Load all verb forms
                cursor.execute('SELECT root, forms FROM verb_forms')
                verb_forms = {}
                for root, forms_json in cursor.fetchall():
                    verb_forms[root] = json.loads(forms_json) if forms_json else {}

                conn.close()
                if verb_forms:
                    print(f"✓ Loaded {len(verb_forms)} verb roots from database")
                    return verb_forms
        except Exception as e:
            pass

        # Fallback to JSON
        try:
            all_verb_forms_path = os.path.join(os.path.dirname(__file__), 'all_verb_forms.json')
            with open(all_verb_forms_path, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load verb forms: {e}")
            return {}

    def load_noun_forms_db(self):
        """Load noun forms from SQLite database or JSON fallback"""
        # Try SQLite database first
        try:
            import sqlite3
            db_path = os.path.join(os.path.dirname(__file__), 'noun_forms.db')
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()

                # Load all noun forms
                cursor.execute('SELECT stem, forms FROM noun_forms')
                noun_forms = {}
                for stem, forms_json in cursor.fetchall():
                    noun_forms[stem] = json.loads(forms_json) if forms_json else {}

                conn.close()
                if noun_forms:
                    print(f"✓ Loaded {len(noun_forms)} noun stems from database")
                    return noun_forms
        except Exception as e:
            pass

        # Fallback to JSON
        try:
            all_noun_forms_path = os.path.join(os.path.dirname(__file__), 'all_noun_forms.json')
            with open(all_noun_forms_path, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load noun forms: {e}")
            return {}

    def load_feedback_data(self):
        """Load user feedback data for learning"""
        try:
            feedback_path = os.path.join(os.path.dirname(__file__), 'user_feedback.json')
            with open(feedback_path, encoding='utf-8') as f:
                self.feedback_data = json.load(f)
        except Exception as e:
            # Initialize empty feedback data
            self.feedback_data = {
                'form_corrections': {},  # form -> list of correct analyses
                'suffix_accuracy': {},    # suffix -> {correct: count, incorrect: count}
                'total_feedback': 0
            }

    def save_feedback_data(self):
        """Save user feedback data"""
        try:
            feedback_path = os.path.join(os.path.dirname(__file__), 'user_feedback.json')
            with open(feedback_path, 'w', encoding='utf-8') as f:
                json.dump(self.feedback_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Error saving feedback: {e}")
            return False

    def record_feedback(self, word: str, correct_analysis: Dict, all_analyses: List[Dict]) -> Dict:
        """
        Record user feedback about which analysis is correct

        Args:
            word: The Prakrit word being analyzed
            correct_analysis: The analysis marked as correct by the user
            all_analyses: All analyses that were returned

        Returns:
            Status dict with success/error message
        """
        try:
            # Record the correction
            if word not in self.feedback_data['form_corrections']:
                self.feedback_data['form_corrections'][word] = []

            self.feedback_data['form_corrections'][word].append({
                'correct_analysis': correct_analysis,
                'timestamp': str(__import__('datetime').datetime.now())
            })

            # Update suffix accuracy tracking
            # Only track suffix correctness, not root correctness
            correct_suffix = correct_analysis.get('suffix') or correct_analysis.get('ending')
            if correct_suffix:
                if correct_suffix not in self.feedback_data['suffix_accuracy']:
                    self.feedback_data['suffix_accuracy'][correct_suffix] = {
                        'correct': 0,
                        'incorrect': 0
                    }

                # Mark this suffix as correct
                self.feedback_data['suffix_accuracy'][correct_suffix]['correct'] += 1

                # Only mark OTHER suffixes as incorrect (not the same suffix with different root)
                # Collect unique suffixes from incorrect analyses
                incorrect_suffixes = set()
                for analysis in all_analyses:
                    if analysis == correct_analysis:
                        continue
                    other_suffix = analysis.get('suffix') or analysis.get('ending')
                    if other_suffix and other_suffix != correct_suffix:
                        incorrect_suffixes.add(other_suffix)

                # Mark each unique incorrect suffix
                for incorrect_suffix in incorrect_suffixes:
                    if incorrect_suffix not in self.feedback_data['suffix_accuracy']:
                        self.feedback_data['suffix_accuracy'][incorrect_suffix] = {
                            'correct': 0,
                            'incorrect': 0
                        }
                    self.feedback_data['suffix_accuracy'][incorrect_suffix]['incorrect'] += 1

            self.feedback_data['total_feedback'] += 1

            # Save to file
            if self.save_feedback_data():
                return {
                    'success': True,
                    'message': 'Feedback recorded successfully',
                    'total_feedback': self.feedback_data['total_feedback']
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to save feedback'
                }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def apply_learned_adjustments(self, analyses: List[Dict]) -> List[Dict]:
        """
        Apply confidence adjustments based on user feedback

        Args:
            analyses: List of analysis dicts

        Returns:
            Analyses with adjusted confidence scores
        """
        for analysis in analyses:
            suffix = analysis.get('suffix') or analysis.get('ending')
            if not suffix:
                continue

            # Check if we have feedback for this suffix
            if suffix in self.feedback_data['suffix_accuracy']:
                stats = self.feedback_data['suffix_accuracy'][suffix]
                correct = stats['correct']
                incorrect = stats['incorrect']
                total = correct + incorrect

                if total > 0:
                    # Calculate accuracy rate
                    accuracy = correct / total

                    # Adjust confidence based on historical accuracy
                    if accuracy > 0.8 and correct >= 3:
                        # High confidence - boost it
                        analysis['confidence'] = min(1.0, analysis['confidence'] + 0.10)
                        analysis['notes'] = analysis.get('notes', []) + [
                            f"Confidence boosted by user feedback ({correct}/{total} correct)"
                        ]
                    elif accuracy < 0.3 and total >= 3:
                        # Low confidence - reduce it
                        analysis['confidence'] = max(0.1, analysis['confidence'] - 0.15)
                        analysis['notes'] = analysis.get('notes', []) + [
                            f"Confidence reduced by user feedback ({correct}/{total} correct)"
                        ]

        # Re-sort by adjusted confidence
        analyses.sort(key=lambda x: x.get('confidence', 0), reverse=True)

        return analyses

    def initialize_suffix_database(self):
        """Initialize comprehensive suffix database with priority and blocking rules"""

        # NOUN SUFFIXES (sorted by length - longest first)
        self.noun_suffixes = {
            # 5-character suffixes
            'hinto': {
                'cases': ['ablative'],
                'numbers': ['singular', 'plural'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': ['a', 'ā', 'A', 'i', 'ī', 'I', 'u', 'ū', 'U', 'e'],
                'blocks': ['o', 'to', 'into'],
                'priority': 5,
                'confidence': 0.95
            },
            'hiMto': {  # With anusvara
                'cases': ['ablative'],
                'numbers': ['singular', 'plural'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': ['a', 'ā', 'A', 'i', 'ī', 'I', 'u', 'ū', 'U', 'e'],
                'blocks': ['o', 'to', 'iMto', 'into'],
                'priority': 5,
                'confidence': 0.95
            },
            'sunto': {
                'cases': ['ablative'],
                'numbers': ['plural'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': ['a', 'ā', 'A', 'i', 'ī', 'I', 'u', 'ū', 'U', 'e'],
                'blocks': ['o', 'to', 'unto'],
                'priority': 5,
                'confidence': 0.95
            },
            'suMto': {  # With anusvara
                'cases': ['ablative'],
                'numbers': ['plural'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': ['a', 'ā', 'A', 'i', 'ī', 'I', 'u', 'ū', 'U', 'e'],
                'blocks': ['o', 'to', 'uMto', 'unto'],
                'priority': 5,
                'confidence': 0.95
            },
            # 3-character suffixes
            'hiM': {
                'cases': ['instrumental'],
                'numbers': ['plural'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': ['a', 'ā', 'A', 'i', 'ī', 'I', 'u', 'ū', 'U', 'e'],
                'blocks': ['M', 'iM'],
                'priority': 3,
                'confidence': 0.85
            },
            'hi~': {
                'cases': ['instrumental'],
                'numbers': ['plural'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': ['a', 'ā', 'A', 'i', 'ī', 'I', 'u', 'ū', 'U', 'e'],
                'blocks': ['~', 'i~'],
                'priority': 3,
                'confidence': 0.85
            },
            'ssa': {
                'cases': ['dative', 'genitive'],
                'numbers': ['singular'],
                'genders': ['masculine', 'neuter'],
                'must_precede': ['a', 'i', 'u'],
                'blocks': ['a', 'sa'],
                'priority': 3,
                'confidence': 0.9
            },
            'mmi': {
                'cases': ['locative'],
                'numbers': ['singular'],
                'genders': ['masculine', 'neuter'],
                'must_precede': ['a', 'i', 'u'],
                'blocks': ['i', 'mi'],
                'priority': 3,
                'confidence': 0.9
            },
            'tto': {
                'cases': ['ablative'],
                'numbers': ['singular', 'plural'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': ['a', 'i', 'u', 'ā', 'ī', 'ū'],
                'blocks': ['o', 'to'],
                'priority': 3,
                'confidence': 0.85
            },
            'suM': {
                'cases': ['locative'],
                'numbers': ['plural'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': ['a', 'ā', 'A', 'i', 'ī', 'I', 'u', 'ū', 'U', 'e'],
                'blocks': ['M', 'uM'],
                'priority': 3,
                'confidence': 0.85
            },
            'NaM': {
                'cases': ['dative', 'genitive'],  # Dative and genitive plural
                'numbers': ['plural'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': ['a', 'ā', 'A', 'i', 'ī', 'I', 'u', 'ū', 'U', 'e'],
                'blocks': ['M', 'aM'],
                'priority': 3,
                'confidence': 0.90
            },
            # Instrumental singular for a-stems (purisa + iNa → puriseNa via a+i→e sandhi).
            # Distinct from dative/genitive plural -Na (which expects an elongated/long
            # stem-final vowel: purisANa). Higher priority than 'Na' so it wins and
            # blocks the dat/gen-plural reading for forms like puriseNa, kuNanteNa.
            'eNa': {
                'cases': ['instrumental'],
                'numbers': ['singular'],
                'genders': ['masculine', 'neuter'],
                'must_precede': [],
                'blocks': ['Na', 'a'],
                'priority': 4,
                'confidence': 0.92
            },
            'iM': {
                'cases': ['nominative', 'accusative'],
                'numbers': ['plural'],
                'genders': ['neuter'],
                'must_precede': ['ā', 'A', 'ī', 'I', 'ū', 'U'],
                'blocks': ['M'],
                'priority': 2,
                'confidence': 0.85
            },
            'i~': {
                'cases': ['nominative', 'accusative'],
                'numbers': ['plural'],
                'genders': ['neuter'],
                'must_precede': ['ā', 'A', 'ī', 'I', 'ū', 'U'],
                'blocks': ['~'],
                'priority': 2,
                'confidence': 0.8
            },
            # 2-character suffixes
            'hi': {
                'cases': ['instrumental'],
                'numbers': ['plural'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': ['a', 'ā', 'A', 'i', 'ī', 'I', 'u', 'ū', 'U', 'e'],
                'blocks': ['i'],
                'priority': 2,
                'confidence': 0.85
            },
            'su': {
                'cases': ['locative'],
                'numbers': ['plural'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': ['a', 'ā', 'A', 'i', 'ī', 'I', 'u', 'ū', 'U', 'e'],
                'blocks': ['u'],
                'priority': 2,
                'confidence': 0.85
            },
            'Na': {
                'cases': ['dative', 'genitive'],  # Dative and genitive plural
                'numbers': ['plural'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': ['a', 'ā', 'A', 'i', 'ī', 'I', 'u', 'ū', 'U', 'e'],
                'blocks': ['a'],
                'priority': 2,
                'confidence': 0.90
            },
            'No': {
                'cases': ['nominative', 'accusative', 'dative', 'genitive'],
                'numbers': ['plural (nom/acc)', 'singular (dat/gen)'],
                'genders': ['masculine'],
                'must_precede': ['i', 'u'],
                'blocks': ['o'],
                'priority': 2,
                'confidence': 0.75
            },
            'Ni': {
                'cases': ['nominative', 'accusative'],
                'numbers': ['plural'],
                'genders': ['neuter'],
                'must_precede': ['ā', 'A', 'ī', 'I', 'ū', 'U'],
                'blocks': ['i'],
                'priority': 2,
                'confidence': 0.8
            },
            # 1-character suffixes (lowest priority)
            'M': {
                'cases': ['accusative', 'nominative'],
                'numbers': ['singular'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': [],
                'blocks': [],
                'priority': 1,
                'confidence': 0.7
            },
            'u': {
                'cases': ['ablative'],
                'numbers': ['singular', 'plural'],
                'genders': ['masculine', 'feminine', 'neuter'],
                'must_precede': [],
                'blocks': [],
                'priority': 1,
                'confidence': 0.60
            },
            'a': {
                'cases': ['nominative', 'vocative'],
                'numbers': ['singular'],
                'genders': ['neuter'],  # Only neuter a-ending in nominative
                'must_precede': [],
                'blocks': [],
                'priority': 1,
                'confidence': 0.5
            },
            # Masculine nominative singular for a-stems (puriso, gAmo, gacchanto)
            # Lower-priority than longer ablatives (tto, hinto, sunto) which already
            # list 'o' in their blocks, so it only matches when no longer suffix wins.
            'o': {
                'cases': ['nominative'],
                'numbers': ['singular'],
                'genders': ['masculine'],
                'must_precede': [],
                'blocks': [],
                'priority': 1,
                'confidence': 0.75
            },
            # Masculine accusative singular and locative singular for a-stems.
            # Magadhi also uses -e for masc nom sg.
            'e': {
                'cases': ['locative'],
                'numbers': ['singular'],
                'genders': ['masculine', 'neuter'],
                'must_precede': [],
                'blocks': [],
                'priority': 1,
                'confidence': 0.6
            },
            # Feminine-specific endings (long vowels as part of stem, NOT stripped as suffix)
            'A': {
                'cases': ['nominative', 'vocative', 'accusative'],
                'numbers': ['singular', 'plural'],
                'genders': ['feminine'],
                'must_precede': [],
                'blocks': [],
                'priority': 0,  # Lowest priority - only match if nothing else matches
                'confidence': 0.85,
                'zero_suffix': True  # This is a stem-final vowel, not a suffix
            },
            'I': {
                'cases': ['nominative', 'vocative'],
                'numbers': ['singular'],
                'genders': ['feminine'],
                'must_precede': [],
                'blocks': [],
                'priority': 0,
                'confidence': 0.85,
                'zero_suffix': True  # This is a stem-final vowel, not a suffix
            },
            'U': {
                'cases': ['nominative', 'vocative'],
                'numbers': ['singular'],
                'genders': ['feminine'],
                'must_precede': [],
                'blocks': [],
                'priority': 0,
                'confidence': 0.85,
                'zero_suffix': True  # This is a stem-final vowel, not a suffix
            }
        }

        # VERB SUFFIXES
        self.verb_endings = {
            # Present tense
            'mi': {'person': 'first', 'number': 'singular', 'tense': 'present', 'confidence': 0.95, 'priority': 2},
            'si': {'person': 'second', 'number': 'singular', 'tense': 'present', 'confidence': 0.95, 'priority': 2},
            'se': {'person': 'second', 'number': 'singular', 'tense': 'present', 'confidence': 0.85, 'priority': 2},
            'di': {'person': 'third', 'number': 'singular', 'tense': 'present', 'confidence': 0.95, 'priority': 2},
            'ti': {'person': 'third', 'number': 'singular', 'tense': 'present', 'confidence': 0.9, 'priority': 2},
            'mo': {'person': 'first', 'number': 'plural', 'tense': 'present', 'confidence': 0.95, 'priority': 2},
            'mu': {'person': 'first', 'number': 'plural', 'tense': 'present', 'confidence': 0.85, 'priority': 2},
            'ma': {'person': 'first', 'number': 'plural', 'tense': 'present', 'confidence': 0.85, 'priority': 2},
            'ha': {'person': 'second', 'number': 'plural', 'tense': 'present', 'confidence': 0.95, 'priority': 2},
            'tha': {'person': 'second', 'number': 'plural', 'tense': 'present', 'confidence': 0.9, 'priority': 3},
            'nti': {'person': 'third', 'number': 'plural', 'tense': 'present', 'confidence': 0.95, 'priority': 3},
            'nte': {'person': 'third', 'number': 'plural', 'tense': 'present', 'confidence': 0.85, 'priority': 3},
            'Mti': {'person': 'third', 'number': 'plural', 'tense': 'present', 'confidence': 0.9, 'priority': 3},
            'Mte': {'person': 'third', 'number': 'plural', 'tense': 'present', 'confidence': 0.85, 'priority': 3},

            # Future tense
            'himi': {'person': 'first', 'number': 'singular', 'tense': 'future', 'confidence': 0.95, 'priority': 4},
            'ssaM': {'person': 'first', 'number': 'singular', 'tense': 'future', 'confidence': 0.95, 'priority': 4},
            'hisi': {'person': 'second', 'number': 'singular', 'tense': 'future', 'confidence': 0.95, 'priority': 4},
            'himo': {'person': 'first', 'number': 'plural', 'tense': 'future', 'confidence': 0.95, 'priority': 4},
            'hinti': {'person': 'third', 'number': 'plural', 'tense': 'future', 'confidence': 0.95, 'priority': 5},
            'issanti': {'person': 'third', 'number': 'plural', 'tense': 'future', 'confidence': 0.9, 'priority': 7},

            # Past tense
            'sI': {'person': 'all', 'number': 'all', 'tense': 'past', 'confidence': 0.95, 'priority': 2},
            'hI': {'person': 'all', 'number': 'all', 'tense': 'past', 'confidence': 0.95, 'priority': 2},
            'hIa': {'person': 'all', 'number': 'all', 'tense': 'past', 'confidence': 0.85, 'priority': 3},
            'Ia': {'person': 'all', 'number': 'all', 'tense': 'past', 'confidence': 0.8, 'priority': 2},

            # Short forms (single character - lowest priority)
            'i': {'person': 'third', 'number': 'singular', 'tense': 'present', 'confidence': 0.7, 'priority': 1},
            'e': {'person': 'third', 'number': 'singular', 'tense': 'present', 'confidence': 0.7, 'priority': 1},
        }

        # PARTICIPLE SUFFIXES
        self.participle_suffixes = {
            # Type 1: Absolutive/Gerund (8 suffixes) - "having done"
            'ttA': {'type': 'absolutive', 'priority': 5, 'confidence': 0.95, 'vowel_insert': True},
            'ettA': {'type': 'absolutive', 'priority': 5, 'confidence': 0.95, 'vowel_insert': False},
            'ittA': {'type': 'absolutive', 'priority': 5, 'confidence': 0.95, 'vowel_insert': False},

            'tUNa': {'type': 'absolutive', 'priority': 5, 'confidence': 0.90, 'vowel_insert': True},
            'etUNa': {'type': 'absolutive', 'priority': 5, 'confidence': 0.90, 'vowel_insert': False},
            'itUNa': {'type': 'absolutive', 'priority': 5, 'confidence': 0.90, 'vowel_insert': False},

            'UNaM': {'type': 'absolutive', 'priority': 5, 'confidence': 0.85, 'vowel_insert': True},
            'eUNaM': {'type': 'absolutive', 'priority': 5, 'confidence': 0.85, 'vowel_insert': False},
            'iUNaM': {'type': 'absolutive', 'priority': 5, 'confidence': 0.85, 'vowel_insert': False},

            # Sanskrit-model infinitive — "to do / in order to do" (kriyArthaka-kRdanta)
            'tuM': {'type': 'infinitive', 'priority': 4, 'confidence': 0.90, 'vowel_insert': True},
            'etuM': {'type': 'infinitive', 'priority': 4, 'confidence': 0.90, 'vowel_insert': False},
            'ituM': {'type': 'infinitive', 'priority': 4, 'confidence': 0.90, 'vowel_insert': False},

            # Jain Prakrit-native purpose form — hetvartha-kRdanta (e.g. gacchiuM = "to go")
            # These are the Prakrit reductions of tuM, distinct from the Sanskrit-model form above
            'uM': {'type': 'hetvartha', 'priority': 3, 'confidence': 0.75, 'vowel_insert': True},
            'euM': {'type': 'hetvartha', 'priority': 3, 'confidence': 0.75, 'vowel_insert': False},
            'iuM': {'type': 'hetvartha', 'priority': 3, 'confidence': 0.75, 'vowel_insert': False},

            'tUANa': {'type': 'absolutive', 'priority': 6, 'confidence': 0.85, 'vowel_insert': True},
            'etUANa': {'type': 'absolutive', 'priority': 6, 'confidence': 0.85, 'vowel_insert': False},
            'itUANa': {'type': 'absolutive', 'priority': 6, 'confidence': 0.85, 'vowel_insert': False},

            'UANa': {'type': 'absolutive', 'priority': 5, 'confidence': 0.80, 'vowel_insert': True},
            'eUANa': {'type': 'absolutive', 'priority': 5, 'confidence': 0.80, 'vowel_insert': False},
            'iUANa': {'type': 'absolutive', 'priority': 5, 'confidence': 0.80, 'vowel_insert': False},

            # Type 3: Present Participle (2 stems, then declined) - "doing"
            # Base stems (will be declined as nouns)
            'anta': {'type': 'present_participle', 'priority': 5, 'confidence': 0.85, 'declined': True, 'vowel_insert': 'a'},
            'enta': {'type': 'present_participle', 'priority': 5, 'confidence': 0.85, 'declined': True, 'vowel_insert': False},
            'inta': {'type': 'present_participle', 'priority': 5, 'confidence': 0.85, 'declined': True, 'vowel_insert': False},

            'amANa': {'type': 'present_participle', 'priority': 6, 'confidence': 0.90, 'declined': True, 'vowel_insert': 'a'},
            'emANa': {'type': 'present_participle', 'priority': 6, 'confidence': 0.90, 'declined': True, 'vowel_insert': False},
            'imANa': {'type': 'present_participle', 'priority': 6, 'confidence': 0.90, 'declined': True, 'vowel_insert': False},

            # Type 4: Past Passive Participle (1 suffix, then declined) - "done"
            'ia': {'type': 'past_passive_participle', 'priority': 4, 'confidence': 0.90, 'declined': True, 'consonant_only': True},
            'eia': {'type': 'past_passive_participle', 'priority': 4, 'confidence': 0.90, 'declined': True, 'consonant_only': True},
            'iia': {'type': 'past_passive_participle', 'priority': 4, 'confidence': 0.90, 'declined': True, 'consonant_only': True},
            # Sanskrit-style PPP (tatsama forms)
            'ita': {'type': 'past_passive_participle', 'priority': 4, 'confidence': 0.82, 'declined': True},
            'eta': {'type': 'past_passive_participle', 'priority': 4, 'confidence': 0.78, 'declined': True},
            # Short absolutives (without -M)
            'UNa': {'type': 'absolutive', 'priority': 4, 'confidence': 0.85, 'vowel_insert': True},
            'eUNa': {'type': 'absolutive', 'priority': 5, 'confidence': 0.88, 'vowel_insert': False},
            'iUNa': {'type': 'absolutive', 'priority': 5, 'confidence': 0.88, 'vowel_insert': False},
            # Present participle without a/e/i prefix
            'mANa': {'type': 'present_participle', 'priority': 5, 'confidence': 0.85, 'declined': True},
            # Future passive participle / gerundive (kRtya)
            'iavva': {'type': 'future_passive_participle', 'priority': 6, 'confidence': 0.92, 'declined': True},
            'eavva': {'type': 'future_passive_participle', 'priority': 6, 'confidence': 0.92, 'declined': True},
            'avva': {'type': 'future_passive_participle', 'priority': 5, 'confidence': 0.85, 'declined': True},
            'itavva': {'type': 'future_passive_participle', 'priority': 6, 'confidence': 0.92, 'declined': True},
            'etavva': {'type': 'future_passive_participle', 'priority': 6, 'confidence': 0.92, 'declined': True},
            'tavva': {'type': 'future_passive_participle', 'priority': 5, 'confidence': 0.88, 'declined': True},
            'aNijja': {'type': 'future_passive_participle', 'priority': 6, 'confidence': 0.90, 'declined': True},
            'iNijja': {'type': 'future_passive_participle', 'priority': 6, 'confidence': 0.90, 'declined': True},
            'eNijja': {'type': 'future_passive_participle', 'priority': 6, 'confidence': 0.90, 'declined': True},
            'Nijja': {'type': 'future_passive_participle', 'priority': 5, 'confidence': 0.82, 'declined': True},
        }

    def detect_script(self, text: str) -> str:
        """Detect if input is Devanagari or Harvard-Kyoto"""
        if any('\u0900' <= c <= '\u097F' for c in text):
            return 'Devanagari'
        return 'HK'

    def transliterate_to_hk(self, text: str) -> str:
        """Convert Devanagari to Harvard-Kyoto"""
        if self.detect_script(text) == 'Devanagari':
            # Use built-in transliterator
            try:
                from devanagari_transliterator import devanagari_to_hk
                return devanagari_to_hk(text)
            except ImportError:
                # Fallback to aksharamukha if available
                if HAS_AKSHARAMUKHA:
                    return aksh_transliterate.process('Devanagari', 'HK', text)
                return text
        return text

    def transliterate_to_devanagari(self, text: str) -> str:
        """Convert Harvard-Kyoto to Devanagari"""
        if not HAS_AKSHARAMUKHA:
            return text
        return aksh_transliterate.process('HK', 'Devanagari', text)

    def normalize_input(self, text: str) -> str:
        """Normalize input text"""
        text = text.strip()
        # Handle anusvara variations
        text = re.sub(r'M(?=[kgcjṭḍtdnpbmyrlvszh])', 'n', text)
        return text

    def generate_anusvara_variants(self, word: str) -> List[str]:
        """
        Generate all valid anusvara/nasal variants for dictionary lookup

        Prakrit phonology: M (anusvara) before consonants can be:
        - Before velars (k, g): ṅ
        - Before palatals (c, j): ñ
        - Before retroflexes (ṭ, ḍ): ṇ
        - Before dentals (t, d, n): n
        - Before labials (p, b, m): m
        - Can also remain as M/ṃ

        Additionally, databases may store nasals in different ways,
        so we generate multiple variants for better matching.

        Args:
            word: Word in HK transliteration

        Returns:
            List of variants including original
        """
        variants = [word]  # Always include original

        # Context-dependent assimilation: M/ṃ before consonants
        # M/ṃ before velars → ṅ
        variant = re.sub(r'[Mṃ](?=[kg])', 'ṅ', word)
        if variant != word:
            variants.append(variant)

        # M/ṃ before palatals → ñ
        variant = re.sub(r'[Mṃ](?=[cj])', 'ñ', word)
        if variant != word:
            variants.append(variant)

        # M/ṃ before retroflexes → ṇ
        variant = re.sub(r'[Mṃ](?=[ṭḍ])', 'ṇ', word)
        if variant != word:
            variants.append(variant)

        # M/ṃ before dentals → n
        variant = re.sub(r'[Mṃ](?=[tdn])', 'n', word)
        if variant != word:
            variants.append(variant)

        # M/ṃ before labials → m
        variant = re.sub(r'[Mṃ](?=[pbm])', 'm', word)
        if variant != word:
            variants.append(variant)

        # M ↔ ṃ conversion
        if 'M' in word:
            variants.append(word.replace('M', 'ṃ'))
        if 'ṃ' in word:
            variants.append(word.replace('ṃ', 'M'))

        # Additional nasal variants for database matching
        # N can be stored as ṇ (retroflex), n (dental), ñ (palatal), ṅ (velar), or m (labial)
        # depending on transcription conventions
        if 'N' in word:
            # Try all nasal variants where N appears
            variants.append(word.replace('N', 'ṇ'))  # Retroflex (common)
            variants.append(word.replace('N', 'n'))  # Dental
            variants.append(word.replace('N', 'ñ'))  # Palatal
            variants.append(word.replace('N', 'ṅ'))  # Velar
            variants.append(word.replace('N', 'M'))  # Anusvara
            variants.append(word.replace('N', 'ṃ'))  # Anusvara (dot)

        # Reverse: try N for other nasals (in case database uses capital N)
        for nasal in ['ṇ', 'ñ', 'ṅ', 'n', 'm']:
            if nasal in word:
                variants.append(word.replace(nasal, 'N'))

        # Remove duplicates while preserving order
        seen = set()
        unique_variants = []
        for v in variants:
            if v not in seen:
                seen.add(v)
                unique_variants.append(v)

        return unique_variants

    def check_attested_verb_form(self, form: str) -> List[Tuple[str, Dict]]:
        """
        Check if a verb form is attested in Turso database or local cache

        Args:
            form: Verb form in HK transliteration

        Returns:
            List of (root, form_info) tuples for all matching rows
        """
        all_results = []
        # Try anusvara variants
        variants = self.generate_anusvara_variants(form)

        # Try Turso database first (direct query is more efficient)
        if self.turso_db and self.turso_db.connected:
            for variant in variants:
                matches = self.turso_db.check_verb_form(variant)
                all_results.extend(matches)

        # Fallback to in-memory cache (only if no Turso results)
        if not all_results and self.all_verb_forms:
            for variant in variants:
                for root, forms in self.all_verb_forms.items():
                    if isinstance(forms, dict):
                        if variant in forms:
                            all_results.append((root, forms[variant]))
                    elif isinstance(forms, list):
                        if variant in forms:
                            all_results.append((root, {}))

        return all_results

    def check_attested_noun_form(self, form: str) -> List[Tuple[str, Dict]]:
        """
        Check if a noun form is attested in Turso database or local cache

        Args:
            form: Noun form in HK transliteration

        Returns:
            List of (stem, form_info) tuples for all matching rows
        """
        all_results = []
        # Try anusvara variants
        variants = self.generate_anusvara_variants(form)

        # Try Turso database first (direct query is more efficient)
        if self.turso_db and self.turso_db.connected:
            for variant in variants:
                matches = self.turso_db.check_noun_form(variant)
                all_results.extend(matches)

        # Fallback to in-memory cache (only if no Turso results)
        if not all_results and self.all_noun_forms:
            for variant in variants:
                for stem, forms in self.all_noun_forms.items():
                    if isinstance(forms, dict):
                        if variant in forms:
                            all_results.append((stem, forms[variant]))
                    elif isinstance(forms, list):
                        if variant in forms:
                            all_results.append((stem, {}))

        return all_results

    def validate_prakrit_characters(self, text: str) -> Tuple[bool, str]:
        """Validate if text contains only valid Prakrit characters"""
        hk_text = self.transliterate_to_hk(text)

        # Forbidden characters in Prakrit
        forbidden = {
            'R': 'retroflex R',
            'RR': 'long retroflex R',
            'lR': 'vocalic L',
            'lRR': 'long vocalic L',
            'H': 'visarga (ः)',
            'S': 'retroflex S (ष)'
        }

        for char, desc in forbidden.items():
            if char in hk_text:
                return False, f"Invalid character '{char}' ({desc}) - not found in Prakrit"

        return True, ""

    def check_attested_form(self, word_hk: str, form_type: str) -> Optional[Dict]:
        """Check if form is attested in JSON databases"""
        if form_type == 'verb':
            # Check in all_verb_forms
            for root, forms in self.all_verb_forms.items():
                if word_hk in forms:
                    return {
                        'root': root,
                        'form': word_hk,
                        'source': 'attested_verb',
                        'confidence': 1.0
                    }
        elif form_type == 'noun':
            # Check in all_noun_forms
            for stem, forms in self.all_noun_forms.items():
                if word_hk in forms:
                    found = forms[word_hk]
                    return {
                        'stem': stem,
                        'form': word_hk,
                        'gender': found.get('gender', 'unknown'),
                        'case': found.get('case', 'unknown'),
                        'number': found.get('number', 'unknown'),
                        'source': 'attested_noun',
                        'confidence': 1.0
                    }
        return None

    def find_suffix_matches(self, word: str, suffix_dict: Dict) -> List[Dict]:
        """Find all possible suffix matches with priority and blocking"""
        matches = []

        # Sort suffixes by priority (longest first)
        sorted_suffixes = sorted(suffix_dict.items(),
                                key=lambda x: (x[1].get('priority', 0), len(x[0])),
                                reverse=True)

        blocked_suffixes = set()

        for suffix, info in sorted_suffixes:
            # Skip if blocked by higher priority match
            if suffix in blocked_suffixes:
                continue

            if word.endswith(suffix):
                base = word[:-len(suffix)] if len(suffix) > 0 else word

                # Validate context (preceding vowel requirements)
                if info.get('must_precede'):
                    if not base or base[-1] not in info['must_precede']:
                        continue

                # Add blocks from this match
                if info.get('blocks'):
                    blocked_suffixes.update(info['blocks'])

                match = {
                    'suffix': suffix,
                    'base': base,
                    'info': info,
                    'priority': info.get('priority', 0)
                }
                matches.append(match)

        return sorted(matches, key=lambda x: x['priority'], reverse=True)

    def is_valid_prakrit_stem(self, stem: str) -> bool:
        """
        Validate if a stem follows Prakrit phonological rules

        Key Prakrit phonological constraints:
        1. NO consonant-ending words - all Prakrit words must end in vowels
        2. Valid ending vowels: a, ā, i, ī, u, ū, e, o
        3. Anusvara (M/ṃ) is allowed as final

        Args:
            stem: The reconstructed stem to validate

        Returns:
            True if valid Prakrit stem, False otherwise
        """
        if not stem or len(stem) < 1:
            return False

        # Get last character
        last_char = stem[-1]

        # Valid Prakrit word endings (all must be vowels or anusvara)
        valid_endings = {'a', 'ā', 'A', 'i', 'ī', 'I', 'u', 'ū', 'U', 'e', 'o', 'M', 'ṃ', '~'}

        # Check if ends with valid character
        if last_char not in valid_endings:
            return False

        return True

    def is_valid_gender_for_stem(self, stem: str, gender: str) -> bool:
        """
        Validate if a gender is valid for a given stem ending

        CRITICAL Prakrit gender rules (based on prakrit-noun-js):
        - Masculine/Neuter: a, i, u endings ONLY
        - Feminine: A, i, I, u, U endings (and a-ending converts to A)

        Therefore:
        - A-ending: FEMININE ONLY
        - I-ending: FEMININE ONLY
        - U-ending: FEMININE ONLY
        - a, i, u endings: ALL genders allowed

        Args:
            stem: The noun stem
            gender: The proposed gender (masculine/feminine/neuter)

        Returns:
            True if gender is valid for this stem, False otherwise
        """
        if not stem:
            return True  # Can't validate

        last_char = stem[-1]

        # A, I, U endings are FEMININE ONLY
        if last_char in ['A', 'I', 'U'] and gender in ['masculine', 'neuter']:
            return False

        # All other combinations are valid
        return True

    def reconstruct_noun_stem(self, base: str, suffix: str, gender: str) -> str:
        """
        Reconstruct noun stem from base and suffix

        Fifth case (ablative) rule:
        - For all ablative suffixes EXCEPT 'tto': last vowel is ELONGATED (a→A, i→I, u→U)
        - For 'tto' suffix: if last vowel is LONG, it is SHORTENED (A→a, I→i, U→u)
        - For a-ending words with 'hinto'/'sunto' plural: a optionally changes to 'e'
        """
        if not base:
            return ''

        # ABLATIVE (5th case) suffixes that ELONGATE the final vowel
        # (All ablative except 'tto')
        ablative_elongate = ['o', 'u', 'hi', 'hiM', 'hi~', 'hinto', 'hiMto', 'sunto', 'suMto']

        if suffix in ablative_elongate:
            # The base has elongated vowel, we need to shorten it to get stem
            # BUT: for A-ending feminine stems, the base IS the stem (no elongation)
            if base.endswith(('A', 'ā')):
                # Two interpretations:
                # 1. A is elongated 'a' → stem is a-ending (masculine/neuter)
                # 2. A is the stem ending → stem is A-ending (feminine)
                if gender == 'feminine':
                    # A-ending feminine stem
                    return base
                else:
                    # a-ending masculine/neuter (elongated to A)
                    return base[:-1] + 'a'
            elif base.endswith(('I', 'ī')):
                # Two interpretations:
                # 1. I is elongated 'i' → stem is i-ending (masculine/neuter)
                # 2. I is the stem ending → stem is I-ending (feminine)
                if gender == 'feminine':
                    # I-ending feminine stem
                    return base
                else:
                    # i-ending masculine/neuter (elongated to I)
                    return base[:-1] + 'i'
            elif base.endswith(('U', 'ū')):
                # Two interpretations:
                # 1. U is elongated 'u' → stem is u-ending (masculine/neuter)
                # 2. U is the stem ending → stem is U-ending (feminine)
                if gender == 'feminine':
                    # U-ending feminine stem
                    return base
                else:
                    # u-ending masculine/neuter (elongated to U)
                    return base[:-1] + 'u'
            elif base.endswith('e'):
                # e could come from a→e (optional change before hinto/sunto)
                return base[:-1] + 'a'
            # If already short vowel, stem is just base + short vowel
            elif base.endswith('a'):
                return base + 'a'
            elif base.endswith('i'):
                return base + 'i'
            elif base.endswith('u'):
                return base + 'u'

        # ABLATIVE 'tto' suffix: SHORTENS long vowels (opposite of others)
        elif suffix == 'tto':
            # Base has short vowel (because long was shortened), so stem has short vowel
            if base.endswith(('a', 'i', 'u')):
                return base
            # If base has long vowel, it means stem also has long vowel
            elif base.endswith(('A', 'ā')):
                return base
            elif base.endswith(('I', 'ī')):
                return base
            elif base.endswith(('U', 'ū')):
                return base
            else:
                # No vowel ending, add default 'a'
                return base + 'a'

        # Instrumental plural (hi, hiM, su, suM): expect elongated vowels
        # (These overlap with ablative_elongate, so handled above)

        # For suffixes attached directly to stem (no vowel change)
        elif suffix in ['ssa', 'mmi', 'No']:
            if base.endswith(('a', 'i', 'u', 'A', 'ā', 'I', 'ī', 'U', 'ū')):
                return base
            return base + 'a'  # default

        # Dative/Genitive plural (Na/NaM)
        elif suffix in ['Na', 'NaM']:
            # These expect elongated vowels too
            if base.endswith(('A', 'ā')):
                return base[:-1] + 'a'
            elif base.endswith(('I', 'ī')):
                return base[:-1] + 'i'
            elif base.endswith(('U', 'ū')):
                return base[:-1] + 'u'
            elif base.endswith('e'):
                return base[:-1] + 'a'
            elif base.endswith(('a', 'i', 'u')):
                return base

        # Nominative/Vocative singular 'e' - from a-stem
        elif suffix == 'e':
            return base + 'a'

        # Instrumental singular '-eNa' for a-stems: base is the consonant skeleton
        # of an a-stem (puris + eNa → purisa; kuNant + eNa → kuNanta).
        elif suffix == 'eNa':
            return base + 'a'

        # Accusative singular 'M'
        elif suffix == 'M':
            return base

        # Consonant-ending base with masc nom sg 'o': default to a-stem.
        # e.g. base 'puris' + 'o' → stem 'purisa'; 'kuNant' + 'o' → 'kuNanta'.
        if suffix == 'o' and base and base[-1] not in 'aAiIuUeoāīū':
            return base + 'a'

        # Default: return base as-is
        return base

    def _candidate_stems(self, hk: str, noun_suffix: str, ninfo: Dict) -> List[str]:
        """Generate multiple candidate stems for a declined form.

        Case endings often absorb or alter the stem-final vowel, so a single
        strip rarely lands on the actual stem. Returns up to 5 candidates
        ordered by most-likely first.
        """
        candidates: List[str] = []
        seen: set = set()

        def push(s: str):
            if s and len(s) >= 2 and s not in seen:
                seen.add(s)
                candidates.append(s)

        if ninfo.get('zero_suffix'):
            push(hk)
            short = {'A': 'a', 'I': 'i', 'U': 'u'}.get(noun_suffix)
            if short and len(hk) >= 1:
                push(hk[:-1] + short)
            return candidates

        base = hk[:-len(noun_suffix)] if noun_suffix else hk
        push(base)
        # Restoring stem-final 'a' is critical: e.g. pucchi → pucchia (PPP -ia of pucch)
        push(base + 'a')
        # a→e alternation: Prakrit a-stem 'a' becomes 'e' before certain case endings
        # in some dialects (e.g. gacchantesu → base gacchante → restore gacchanta)
        if base.endswith('e') and len(base) > 1:
            push(base[:-1] + 'a')
        for g in ninfo.get('genders', []):
            rs = self.reconstruct_noun_stem(base, noun_suffix, g)
            push(rs)
        return candidates[:5]

    def _find_verb_root(self, base: str) -> str:
        """Return the best attested verb root for a given base form.

        Tries the longest matching prefix first, then falls back to
        sandhi-reversed candidates, then hiatus-y removal. Returns base
        itself if nothing attested.
        """
        if not base:
            return base

        # 1. Exact match
        if base in self.verb_roots:
            return base

        # 2. Vowel restoration: when a vowel-initial suffix like 'anta'/'amANa'
        # attaches, the root's final vowel is elided (puccha + anta → pucchanta).
        # After stripping the suffix we have a consonant-final base; restore the
        # vowel by trying base + a/i/e.
        vowels = 'aAiIuUeo'
        if base[-1] not in vowels:
            for v in ('a', 'i', 'e'):
                if base + v in self.verb_roots:
                    return base + v

        # 3. Sandhi reversal (e→ī, o→ū, etc.)
        for cand, _ in self.apply_vowel_sandhi_reverse(base):
            if cand in self.verb_roots:
                return cand

        # 4. Hiatus-y removal: root+y appears when a vowel-initial suffix follows
        # a vowel-final root (e.g. nI + anta → nIyanta; strip 'anta' → 'nIy' → 'nI')
        hiatus_base = self._strip_hiatus_y(base)
        if hiatus_base:
            if hiatus_base in self.verb_roots:
                return hiatus_base
            for cand, _ in self.apply_vowel_sandhi_reverse(hiatus_base):
                if cand in self.verb_roots:
                    return cand
            if hiatus_base[-1] not in vowels:
                for v in ('a', 'i', 'e'):
                    if hiatus_base + v in self.verb_roots:
                        return hiatus_base + v

        # 5. Conservative one-character trim: covers cases like gaccha → gacch
        # where the final stem-vowel was already absorbed. Strictly at most 1
        # char less to prevent spurious short matches (muN → mu, jAN → jA).
        if len(base) >= 4 and base[:-1] in self.verb_roots:
            return base[:-1]

        # 6. Return base unchanged — better than a wrong shorter root.
        return base

    _HIATUS_VOWELS = frozenset('aAiIuUeo')

    def _strip_hiatus_y(self, base: str) -> Optional[str]:
        """
        Prakrit inserts 'y' between adjacent vowels (hiatus bridge).
        E.g.: root nI + suffix anta → nIyanta; after stripping suffix: nIy.
        The trailing 'y' preceded by a vowel is the hiatus filler — strip it
        to recover the root. Returns None when the rule does not apply.
        """
        if len(base) >= 2 and base[-1] == 'y' and base[-2] in self._HIATUS_VOWELS:
            return base[:-1]
        return None

    def analyze_as_noun(self, word_hk: str) -> List[Dict]:
        """Analyze word as a Prakrit noun with attested form validation"""
        results = []

        # First check if form is attested in noun_forms.db
        attested_matches = self.check_attested_noun_form(word_hk)
        is_attested = len(attested_matches) > 0
        attested_stems = {stem for stem, _ in attested_matches}

        for attested_stem, form_info in attested_matches:
            # High confidence for attested forms
            analysis = {
                'form': word_hk,
                'stem': attested_stem,
                'type': 'noun',
                'source': 'attested_form',
                'confidence': 1.0,
                'notes': []
            }

            # Add grammatical info if available from form_info
            if form_info and isinstance(form_info, dict):
                case = form_info.get('case', 'unknown')
                number = form_info.get('number', 'unknown')
                gender = form_info.get('gender', 'unknown')
                analysis.update({
                    'case': case,
                    'number': number,
                    'gender': gender
                })
                # Add Sanskrit terms
                if case != 'unknown':
                    analysis['sanskrit_case'] = SANSKRIT_TERMS.get(case, case)
                if number != 'unknown':
                    analysis['sanskrit_number'] = SANSKRIT_TERMS.get(number, number)
                if gender != 'unknown':
                    analysis['sanskrit_gender'] = SANSKRIT_TERMS.get(gender, gender)

            results.append(analysis)
        # Also try ending-based analysis for additional insights

        # Find suffix matches
        suffix_matches = self.find_suffix_matches(word_hk, self.noun_suffixes)

        for match in suffix_matches[:10]:  # Limit to top 10 matches
            suffix = match['suffix']
            base = match['base']
            info = match['info']

            # Try each gender possibility
            for gender in info.get('genders', []):
                # For zero-suffix cases (A, I, U feminine endings), the base IS the stem
                if info.get('zero_suffix', False):
                    stem = base + suffix  # Reconstruct the full word as the stem
                else:
                    stem = self.reconstruct_noun_stem(base, suffix, gender)

                if not stem or len(stem) < 2:
                    continue

                # Validate Prakrit phonology: no consonant-ending stems
                if not self.is_valid_prakrit_stem(stem):
                    continue

                # Validate gender for this stem ending
                # CRITICAL: No a-ending, i-ending, or u-ending feminine words!
                if not self.is_valid_gender_for_stem(stem, gender):
                    continue

                # Create analysis for each case possibility
                for case in info.get('cases', []):
                    for number in info.get('numbers', []):
                        confidence = info.get('confidence', 0.5)

                        # Boost confidence for good stem matches
                        if stem.endswith(('a', 'i', 'u', 'ā', 'ī', 'ū')):
                            confidence += 0.05

                        # Extra confidence boost if stem matches attested stem
                        if is_attested and stem in attested_stems:
                            confidence = min(confidence + 0.25, 0.95)  # High but not 1.0

                        analysis = {
                            'form': word_hk,
                            'stem': stem,
                            'suffix': suffix if not info.get('zero_suffix') else '',
                            'case': case,
                            'number': number,
                            'gender': gender,
                            'type': 'noun',
                            'source': 'attested_stem_match' if is_attested else 'ending_based_guess',
                            'confidence': min(confidence, 1.0),
                            'notes': [f"Ending-based analysis: stem-final '{suffix}' suggests {case} {number}" if info.get('zero_suffix') else f"Ending-based analysis: suffix '{suffix}' suggests {case} {number}"]
                        }

                        # Add Sanskrit terms
                        analysis['sanskrit_case'] = SANSKRIT_TERMS.get(case, case)
                        analysis['sanskrit_number'] = SANSKRIT_TERMS.get(number, number)
                        analysis['sanskrit_gender'] = SANSKRIT_TERMS.get(gender, gender)

                        # Add stem ending type (e.g., a-ending, A-ending)
                        if stem:
                            stem_ending = stem[-1]
                            if stem_ending in NOUN_ENDING_TYPES:
                                analysis['stem_ending_type'] = NOUN_ENDING_TYPES[stem_ending]

                        # Add note if stem matches attested
                        if is_attested and stem in attested_stems:
                            analysis['notes'].append(f"Stem '{stem}' matches attested form")

                        results.append(analysis)

        return results

    def apply_vowel_sandhi_reverse(self, base: str) -> List[Tuple[str, str]]:
        """
        Reverse vowel sandhi transformations to find potential verb roots.
        Returns list of (potential_root, sandhi_rule) tuples.

        Prakrit vowel sandhi rules:
        - ī (I) + consonant suffix → e (NI + mo → Nemo)
        - ū (U) + consonant suffix → o (BhU + ti → Bhoti)
        - ai/e → A/ā in some contexts
        - o → U/ū in some contexts
        """
        candidates = []

        if not base:
            return candidates

        # Rule 1: e → I (ī)
        # Example: "Ne" from "Nemo" → "NI" root
        if base.endswith('e'):
            i_root = base[:-1] + 'I'
            candidates.append((i_root, 'e→ī sandhi'))
            # Also try short i
            i_short_root = base[:-1] + 'i'
            candidates.append((i_short_root, 'e→i sandhi'))

        # Rule 2: o → U (ū)
        # Example: "Bho" from "Bhoti" → "BhU" root
        if base.endswith('o'):
            u_root = base[:-1] + 'U'
            candidates.append((u_root, 'o→ū sandhi'))
            # Also try short u
            u_short_root = base[:-1] + 'u'
            candidates.append((u_short_root, 'o→u sandhi'))

        # Rule 3: a → A (ā)
        if base.endswith('a'):
            a_root = base[:-1] + 'A'
            candidates.append((a_root, 'a→ā extension'))

        # Rule 4: Also check for base + A/I/U directly (no sandhi)
        for vowel in ['A', 'I', 'U', 'a', 'i', 'u']:
            candidates.append((base + vowel, f'vowel-ending +{vowel}'))

        return candidates

    def analyze_as_verb(self, word_hk: str) -> List[Dict]:
        """Analyze word as a Prakrit verb with attested form validation and vowel sandhi support"""
        results = []

        # First check if form is attested in verb_forms.db
        attested_matches = self.check_attested_verb_form(word_hk)
        is_attested = len(attested_matches) > 0
        attested_roots = {root for root, _ in attested_matches}

        for attested_root, form_info in attested_matches:
            # High confidence for attested forms
            analysis = {
                'form': word_hk,
                'root': attested_root,
                'type': 'verb',
                'source': 'attested_form',
                'confidence': 1.0,
                'notes': []
            }

            # Add grammatical info if available from form_info
            if form_info and isinstance(form_info, dict):
                tense = form_info.get('tense', 'unknown')
                voice = form_info.get('voice', 'active')  # active/passive
                mood = form_info.get('mood', 'indicative')
                person = form_info.get('person', 'unknown')
                number = form_info.get('number', 'unknown')
                analysis.update({
                    'tense': tense,
                    'voice': voice,
                    'mood': mood,
                    'dialect': form_info.get('dialect', 'standard'),
                    'person': person,
                    'number': number
                })
                # Add Sanskrit terms
                if tense != 'unknown':
                    analysis['sanskrit_tense'] = SANSKRIT_TERMS.get(tense, tense)
                if voice and voice != 'unknown':
                    analysis['sanskrit_voice'] = SANSKRIT_TERMS.get(voice, voice)
                if mood and mood != 'unknown':
                    analysis['sanskrit_mood'] = SANSKRIT_TERMS.get(mood, mood)
                if person != 'unknown':
                    analysis['sanskrit_person'] = SANSKRIT_TERMS.get(person, person)
                if number != 'unknown':
                    analysis['sanskrit_number'] = SANSKRIT_TERMS.get(number, number)

            results.append(analysis)
        # Also try ending-based analysis for additional insights

        # Find ending matches
        ending_matches = self.find_suffix_matches(word_hk, self.verb_endings)

        for match in ending_matches[:10]:  # Limit to top 10
            ending = match['suffix']
            base = match['base']
            info = match['info']

            # Collect ALL potential roots (both direct and sandhi)
            root_candidates = []

            # Strategy 1: Direct substring matches
            for i in range(len(base), 0, -1):
                subroot = base[:i]
                if subroot in self.verb_roots:
                    root_candidates.append({
                        'root': subroot,
                        'method': 'direct_match',
                        'sandhi_note': None,
                        'confidence_boost': 0.15
                    })

            # Strategy 2: Vowel sandhi reversals
            sandhi_candidates = self.apply_vowel_sandhi_reverse(base)
            for candidate_root, sandhi_rule in sandhi_candidates:
                if candidate_root in self.verb_roots:
                    root_candidates.append({
                        'root': candidate_root,
                        'method': 'sandhi_reversal',
                        'sandhi_note': sandhi_rule,
                        'confidence_boost': 0.20  # Slightly higher for sandhi (more sophisticated)
                    })
                # Also try partial matches for compound roots
                for i in range(len(candidate_root), 0, -1):
                    if candidate_root[:i] in self.verb_roots:
                        root_candidates.append({
                            'root': candidate_root[:i],
                            'method': 'sandhi_reversal_partial',
                            'sandhi_note': sandhi_rule,
                            'confidence_boost': 0.12
                        })

            # If no attested root found, use the base as a guess
            if not root_candidates:
                root_candidates.append({
                    'root': base,
                    'method': 'unattested_guess',
                    'sandhi_note': None,
                    'confidence_boost': -0.1
                })

            # Create analysis for each root candidate
            for candidate in root_candidates:
                # Note: Verb roots CAN end in consonants (e.g., muN, jAN)
                # Only the final inflected forms must end in vowels
                # So we do NOT apply phonological validation here

                confidence = info.get('confidence', 0.5) + candidate['confidence_boost']

                # Extra confidence boost if root matches attested root
                if is_attested and candidate['root'] in attested_roots:
                    confidence = min(confidence + 0.25, 0.95)  # High but not 1.0

                if candidate['sandhi_note']:
                    note = f"Root '{candidate['root']}' found via vowel sandhi ({candidate['sandhi_note']})"
                    source = 'sandhi_analysis'
                elif candidate['method'] == 'direct_match':
                    note = f"Root '{candidate['root']}' found in verb list"
                    source = 'ending_based_guess'
                else:
                    note = "Root not attested - guessed from form"
                    source = 'ending_based_guess'

                # Override source if matches attested
                if is_attested and candidate['root'] in attested_roots:
                    source = 'attested_root_match'

                tense = info.get('tense')
                voice = 'active'  # Default for ending-based analysis
                mood = 'indicative'  # Default for ending-based analysis
                person = info.get('person')
                number = info.get('number')

                analysis = {
                    'form': word_hk,
                    'root': candidate['root'],
                    'ending': ending,
                    'tense': tense,
                    'voice': voice,
                    'mood': mood,
                    'dialect': 'standard',  # Default for ending-based analysis
                    'person': person,
                    'number': number,
                    'type': 'verb',
                    'source': source,
                    'confidence': min(max(confidence, 0.1), 1.0),
                    'notes': [f"Ending-based analysis: {note}"]
                }

                # Add Sanskrit terms
                if tense:
                    analysis['sanskrit_tense'] = SANSKRIT_TERMS.get(tense, tense)
                if voice:
                    analysis['sanskrit_voice'] = SANSKRIT_TERMS.get(voice, voice)
                if mood:
                    analysis['sanskrit_mood'] = SANSKRIT_TERMS.get(mood, mood)
                if person:
                    analysis['sanskrit_person'] = SANSKRIT_TERMS.get(person, person)
                if number:
                    analysis['sanskrit_number'] = SANSKRIT_TERMS.get(number, number)

                # Add note if root matches attested
                if is_attested and candidate['root'] in attested_roots:
                    analysis['notes'].append(f"Root '{candidate['root']}' matches attested form")

                results.append(analysis)

        return results

    def analyze_as_participle(self, word_hk: str) -> List[Dict]:
        """Analyze word as a Prakrit participle"""
        results = []

        # First check if form is attested in participle_forms database
        if self.turso_db and self.turso_db.connected:
            variants = self.generate_anusvara_variants(word_hk)
            for variant in variants:
                matches = self.turso_db.check_participle_form(variant)
                for root, info in matches:
                    participle_type = info.get('participle_type')
                    analysis = {
                        'form': word_hk,
                        'root': root,
                        'type': 'participle',
                        'participle_type': participle_type,
                        'suffix': info.get('suffix'),
                        'source': 'attested_form',
                        'confidence': 1.0,
                        'notes': []
                    }

                    # Add Sanskrit term for participle type
                    if participle_type:
                        analysis['sanskrit_term'] = SANSKRIT_TERMS.get(participle_type, participle_type)

                    # Add declension info if available (for declined participles)
                    if info.get('gender'):
                        gender = info.get('gender')
                        case = info.get('case')
                        number = info.get('number')
                        analysis['gender'] = gender
                        analysis['case'] = case
                        analysis['number'] = number
                        # Add Sanskrit terms for declined participles
                        if gender:
                            analysis['sanskrit_gender'] = SANSKRIT_TERMS.get(gender, gender)
                        if case:
                            analysis['sanskrit_case'] = SANSKRIT_TERMS.get(case, case)
                        if number:
                            analysis['sanskrit_number'] = SANSKRIT_TERMS.get(number, number)

                    results.append(analysis)

        # Ending-based analysis
        suffix_matches = self.find_suffix_matches(word_hk, self.participle_suffixes)

        for match in suffix_matches[:10]:
            suffix = match['suffix']
            base = match['base']
            info = match['info']

            # For consonant-only PPP (e.g. -ia): base must end in a consonant
            _vowels = {'a', 'ā', 'A', 'i', 'ī', 'I', 'u', 'ū', 'U', 'e', 'o', 'M', 'ṃ'}
            if info.get('consonant_only') and (not base or base[-1] in _vowels):
                continue

            root = self._find_verb_root(base)
            potential_roots = [root]
            # Detect if hiatus-y was resolved to show in notes
            hiatus_fired = (
                root != base and
                base.endswith('y') and
                len(base) >= 2 and base[-2] in self._HIATUS_VOWELS
            )

            for root in potential_roots:
                confidence = info.get('confidence', 0.7)

                # Boost confidence if root is in verb_roots
                if root in self.verb_roots:
                    confidence += 0.15

                participle_type = info.get('type')
                notes = [f"Participle: {participle_type} with suffix '{suffix}'"]
                if hiatus_fired:
                    notes.append("Hiatus 'y' resolved between adjacent vowels")

                analysis = {
                    'form': word_hk,
                    'root': root,
                    'suffix': suffix,
                    'type': 'participle',
                    'participle_type': participle_type,
                    'source': 'ending_based_guess',
                    'confidence': min(confidence, 1.0),
                    'notes': notes
                }

                # Add Sanskrit term for participle type
                if participle_type:
                    analysis['sanskrit_term'] = SANSKRIT_TERMS.get(participle_type, participle_type)

                # Add note if declined
                if info.get('declined'):
                    analysis['notes'].append('Declined form - analyze as noun for case/gender/number')
                    analysis['declined'] = True

                results.append(analysis)

        return results

    def is_participle_stem(self, stem: str) -> Tuple[bool, Optional[Dict]]:
        """
        Check if a stem is a participle stem and return participle info

        Returns:
            (is_participle, participle_info) where participle_info contains:
            - root: verbal root
            - suffix: participle suffix
            - type: participle type
            - confidence: confidence score
        """
        # Normalize anusvara variants in the stem before suffix matching.
        # Handles cases like aMta (M before dental t) → anta so the suffix
        # table entry 'anta' matches regardless of how the nasal was spelled.
        stem = self.normalize_input(stem)

        # Check against known participle suffixes
        for suffix, info in self.participle_suffixes.items():
            if stem.endswith(suffix):
                base = stem[:-len(suffix)]

                if not base:
                    continue

                # Use _find_verb_root for comprehensive root recovery:
                # tries all prefix lengths, vowel sandhi reversal, and hiatus-y removal.
                # Returns base unchanged when nothing attested — we still produce an
                # analysis in that case, just without the attested-root confidence boost.
                hiatus_resolved = False
                root = self._find_verb_root(base)
                root_attested = root in self.verb_roots

                # Detect if hiatus-y stripping was responsible for finding the root
                if root_attested and root != base:
                    stripped = self._strip_hiatus_y(base)
                    if stripped and (stripped == root or root.startswith(stripped)):
                        hiatus_resolved = True

                confidence = info.get('confidence', 0.7)
                if root_attested:
                    confidence += 0.15
                else:
                    # No attested root found — lower confidence but still produce a result
                    # so that declined present-participle forms aren't silently dropped.
                    confidence -= 0.10

                result = {
                    'root': root,
                    'suffix': suffix,
                    'type': info.get('type'),
                    'declined': info.get('declined', False),
                    'confidence': max(min(confidence, 1.0), 0.1),
                    'sanskrit_term': SANSKRIT_TERMS.get(info.get('type'), info.get('type'))
                }
                if hiatus_resolved:
                    result['hiatus_resolved'] = True
                return True, result

        return False, None

    def analyze_as_declined_participle(self, word_hk: str) -> List[Dict]:
        """
        Analyze word as a declined participle (participle stem + noun ending).

        Handles forms like pucchamANo = puccha + mANa + o (masc nom-sg of the
        present participle). Uses multiple candidate stems per noun suffix to
        catch vowel-absorption cases the simple strip misses (e.g. pucchio →
        strip 'o' → pucchi → +a → pucchia, PPP -ia of pucch).
        """
        results = []
        seen_sigs: set = set()

        for noun_suffix, suffix_info in self.noun_suffixes.items():
            if not noun_suffix or not word_hk.endswith(noun_suffix):
                continue

            for stem in self._candidate_stems(word_hk, noun_suffix, suffix_info):
                is_part, part_info = self.is_participle_stem(stem)
                if not is_part:
                    continue

                # Deduplicate: one result per (stem, noun_ending, participle_suffix, type)
                sig = (stem, noun_suffix, part_info.get('suffix'), part_info.get('type'))
                if sig in seen_sigs:
                    continue
                seen_sigs.add(sig)

                root = part_info['root']
                attested = root in self.verb_roots
                conf = part_info['confidence'] + (0.08 if attested else -0.05)

                notes = [
                    f"Declined participle: {part_info['sanskrit_term']}",
                    f"Root: '{root}' + participle suffix '{part_info['suffix']}'",
                    f"Declined with noun ending '-{noun_suffix}'"
                ]
                if part_info.get('type') == 'present_participle':
                    notes.insert(0, "Nominal declension of present participle (vartamAna-kRdanta): root + kRt suffix + nominal case ending")
                if part_info.get('hiatus_resolved'):
                    notes.append("Hiatus 'y' resolved between adjacent vowels")

                analysis = {
                    'form': word_hk,
                    'stem': stem,
                    'root': root,
                    'type': 'participle',
                    'participle_type': part_info['type'],
                    'sanskrit_term': part_info['sanskrit_term'],
                    'participle_suffix': part_info['suffix'],
                    'noun_ending': noun_suffix,
                    'source': 'declined_participle',
                    'confidence': min(conf, 0.97),
                    'notes': notes
                }

                cases = suffix_info.get('cases', [])
                numbers = suffix_info.get('numbers', [])
                genders = suffix_info.get('genders', [])

                if cases:
                    if len(cases) == 1:
                        analysis['case'] = cases[0]
                        analysis['sanskrit_case'] = SANSKRIT_TERMS.get(cases[0], cases[0])
                    else:
                        analysis['cases'] = cases
                        analysis['sanskrit_cases'] = [SANSKRIT_TERMS.get(c, c) for c in cases]

                if numbers:
                    if len(numbers) == 1:
                        analysis['number'] = numbers[0]
                        analysis['sanskrit_number'] = SANSKRIT_TERMS.get(numbers[0], numbers[0])
                    else:
                        analysis['numbers'] = numbers

                if genders:
                    if len(genders) == 1:
                        analysis['gender'] = genders[0]
                        analysis['sanskrit_gender'] = SANSKRIT_TERMS.get(genders[0], genders[0])
                    else:
                        analysis['genders'] = genders

                if stem:
                    stem_ending = stem[-1]
                    if stem_ending in NOUN_ENDING_TYPES:
                        analysis['stem_ending_type'] = NOUN_ENDING_TYPES[stem_ending]

                results.append(analysis)

        return results

    def parse(self, text: str) -> Dict:
        """Main parsing function - unified analysis"""
        # Validate input
        is_valid, error_msg = self.validate_prakrit_characters(text)
        if not is_valid:
            return {
                'success': False,
                'error': error_msg,
                'suggestions': ['Check input for forbidden characters', 'Use proper Prakrit transliteration']
            }

        # Transliterate first so Devanagari anusvara (ं → M) is visible to normalize_input,
        # then normalize so M+dental (aMta → anta) is resolved before any analysis.
        original_script = self.detect_script(text)
        word_hk = self.normalize_input(self.transliterate_to_hk(text))

        # Analyze as noun, verb, and participle
        noun_analyses = self.analyze_as_noun(word_hk)
        verb_analyses = self.analyze_as_verb(word_hk)
        participle_analyses = self.analyze_as_participle(word_hk)
        declined_participle_analyses = self.analyze_as_declined_participle(word_hk)

        # Combine and sort by confidence
        # Prioritize declined participles as they are more specific
        all_analyses = declined_participle_analyses + participle_analyses + noun_analyses + verb_analyses
        all_analyses.sort(key=lambda x: x.get('confidence', 0), reverse=True)

        # Apply learned adjustments from user feedback
        all_analyses = self.apply_learned_adjustments(all_analyses)

        # Add dictionary meanings if dictionary is loaded
        if self.dictionary:
            for analysis in all_analyses:
                lookup_word = None

                if analysis.get('type') == 'noun':
                    lookup_word = analysis.get('stem')
                elif analysis.get('type') == 'verb':
                    lookup_word = analysis.get('root')
                elif analysis.get('type') == 'participle':
                    lookup_word = analysis.get('root')

                if lookup_word:
                    try:
                        # Try anusvara variants for better dictionary matching
                        # Dictionary is in Devanagari, so M/n/N variations matter
                        variants = self.generate_anusvara_variants(lookup_word)

                        entries = None
                        matched_variant = None

                        # Try each variant until we find a match
                        for variant in variants:
                            entries = self.dictionary.lookup(variant, script='HK')
                            if entries:
                                matched_variant = variant
                                break

                        if entries:
                            entry = entries[0]
                            analysis['dictionary'] = {
                                'headword_devanagari': entry.get('headword_devanagari', ''),
                                'sanskrit_equivalent': entry.get('sanskrit_equivalent', []),
                                'meanings': [m.get('definition', '') for m in entry.get('meanings', [])[:3]],
                                'is_desya': entry.get('is_desya', False)
                            }
                            # Add note if variant was used
                            if matched_variant != lookup_word:
                                analysis['dictionary']['matched_variant'] = matched_variant
                    except:
                        pass  # Dictionary lookup is optional

        # Add Devanagari forms if input was HK
        if original_script == 'HK':
            for analysis in all_analyses:
                if 'form' in analysis:
                    analysis['devanagari'] = self.transliterate_to_devanagari(analysis['form'])
                if 'stem' in analysis:
                    analysis['stem_devanagari'] = self.transliterate_to_devanagari(analysis['stem'])
                if 'root' in analysis:
                    analysis['root_devanagari'] = self.transliterate_to_devanagari(analysis['root'])

        # Take top 15 by confidence, but guarantee at least one analysis per type
        # so that e.g. a declined participle isn't crowded out by many attested noun hits
        top = all_analyses[:15]
        seen_types = {a.get('type') for a in top}
        for a in all_analyses[15:]:
            if a.get('type') not in seen_types:
                top.append(a)
                seen_types.add(a.get('type'))

        return {
            'success': True,
            'original_form': text,
            'hk_form': word_hk,
            'script': original_script,
            'data_source': self.data_source,
            'analyses': top,
            'total_found': len(all_analyses)
        }

    def parse_passage(self, text: str, max_workers: int = 8) -> dict:
        """Analyze every word in a passage in parallel using a thread pool.

        Each token is dispatched to self.parse() concurrently. This is ideal
        for the I/O-bound Turso HTTP queries: a 20-word verse completes in
        roughly the same wall-clock time as a single-word lookup.

        Punctuation tokens (।, ॥, |, commas, etc.) are passed through
        unchanged without being analyzed.

        Args:
            text:        Passage in Devanagari or Harvard-Kyoto.
            max_workers: Thread pool size (default 8 — sufficient for a
                         typical verse without hammering Turso).
        Returns:
            dict with 'tokens' list (order preserved) and 'word_count'.
        """
        PUNCT_RE = re.compile(r'^[।॥|.,;:!?()\-\'"]+$')

        raw_tokens = text.strip().split()
        if not raw_tokens:
            return {'success': True, 'passage': text, 'tokens': [], 'word_count': 0}

        token_list: List[dict] = []
        for chunk in raw_tokens:
            if PUNCT_RE.match(chunk):
                token_list.append({'text': chunk, 'is_punct': True})
            else:
                core = chunk.strip('।॥|.,;:!?()-\'"')
                token_list.append({'text': chunk, 'core': core or chunk, 'is_punct': False})

        results: List[dict] = [None] * len(token_list)  # type: ignore[list-item]

        def analyze_one(idx: int) -> Tuple[int, dict]:
            tok = token_list[idx]
            if tok['is_punct']:
                return idx, {'token': tok['text'], 'is_punct': True}
            try:
                parsed = self.parse(tok['core'])
                analyses = parsed.get('analyses', [])
                return idx, {
                    'token': tok['text'],
                    'core': tok['core'],
                    'is_punct': False,
                    'analyses': analyses,
                    'auto_selected': analyses[0] if analyses else None,
                    'total_found': parsed.get('total_found', 0),
                    'hk_form': parsed.get('hk_form', tok['core']),
                }
            except Exception as exc:
                return idx, {
                    'token': tok['text'],
                    'core': tok['core'],
                    'is_punct': False,
                    'analyses': [],
                    'auto_selected': None,
                    'total_found': 0,
                    'error': str(exc),
                }

        n_workers = min(max_workers, len(token_list))
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(analyze_one, i): i for i in range(len(token_list))}
            for future in as_completed(futures):
                idx, tok_result = future.result()
                results[idx] = tok_result

        word_count = sum(1 for t in results if t and not t.get('is_punct'))
        return {
            'success': True,
            'passage': text,
            'tokens': results,
            'word_count': word_count,
        }

# Initialize parser
parser = PrakritUnifiedParser()

# Flask routes (only if Flask is available)
if HAS_FLASK:
    @app.route('/', methods=['GET'])
    def index():
        return render_template('unified_analyzer.html')

    @app.route('/api/parse', methods=['POST', 'OPTIONS'])
    def api_parse():
        """API endpoint for parsing"""
        if request.method == 'OPTIONS':
            response = jsonify({'status': 'ok'})
            response.headers.add('Access-Control-Allow-Origin', '*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
            response.headers.add('Access-Control-Allow-Methods', 'POST')
            return response

        # Try to get data from multiple sources
        try:
            data = request.get_json(force=True, silent=True)
        except:
            data = None

        if not data:
            data = request.form.to_dict()

        if not data:
            try:
                data = {'form': request.data.decode('utf-8')}
            except:
                data = {}

        form = data.get('form', '')

        if not form or not form.strip():
            return jsonify({
                'success': False,
                'error': 'Please provide a Prakrit word or form'
            }), 400

        try:
            result = parser.parse(form)
            response = jsonify(result)
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f'Parser error: {str(e)}'
            }), 500

    @app.route('/api/analyze', methods=['POST', 'OPTIONS'])
    def api_analyze():
        """Backward compatibility with old /analyze endpoint"""
        if request.method == 'OPTIONS':
            response = jsonify({'status': 'ok'})
            response.headers.add('Access-Control-Allow-Origin', '*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
            response.headers.add('Access-Control-Allow-Methods', 'POST')
            return response

        # Try to get data from multiple sources
        try:
            data = request.get_json(force=True, silent=True)
        except:
            data = None

        if not data:
            data = request.form.to_dict()

        if not data:
            try:
                data = {'verb_form': request.data.decode('utf-8')}
            except:
                data = {}

        verb_form = data.get('verb_form', '')

        if not verb_form:
            return jsonify({
                'success': False,
                'error': 'Please provide a verb form'
            }), 400

        try:
            result = parser.parse(verb_form)

            # Transform to old format
            if result['success']:
                response = jsonify({
                    'results': result['analyses']
                })
            else:
                response = jsonify({
                    'error': result.get('error'),
                    'suggestions': result.get('suggestions', [])
                })

            response.headers.add('Access-Control-Allow-Origin', '*')
            return response
        except Exception as e:
            return jsonify({
                'error': str(e)
            }), 500

    @app.route('/api/feedback', methods=['POST', 'OPTIONS'])
    def api_feedback():
        """API endpoint for submitting user feedback"""
        if request.method == 'OPTIONS':
            response = jsonify({'status': 'ok'})
            response.headers.add('Access-Control-Allow-Origin', '*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
            response.headers.add('Access-Control-Allow-Methods', 'POST')
            return response

        # Try to get data from multiple sources
        try:
            data = request.get_json(force=True, silent=True)
        except:
            data = None

        if not data:
            data = request.form.to_dict()

        word = data.get('word', '')
        correct_analysis_index = data.get('correct_index')
        all_analyses = data.get('all_analyses', [])

        if not word or correct_analysis_index is None or not all_analyses:
            return jsonify({
                'success': False,
                'error': 'Missing required fields: word, correct_index, all_analyses'
            }), 400

        try:
            correct_analysis_index = int(correct_analysis_index)
            if correct_analysis_index < 0 or correct_analysis_index >= len(all_analyses):
                return jsonify({
                    'success': False,
                    'error': 'Invalid correct_index'
                }), 400

            correct_analysis = all_analyses[correct_analysis_index]

            # Record the feedback
            result = parser.record_feedback(word, correct_analysis, all_analyses)

            response = jsonify(result)
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response

        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/feedback/stats', methods=['GET'])
    def api_feedback_stats():
        """Get feedback statistics"""
        try:
            stats = {
                'total_feedback': parser.feedback_data['total_feedback'],
                'unique_forms': len(parser.feedback_data['form_corrections']),
                'suffix_stats': parser.feedback_data['suffix_accuracy']
            }

            response = jsonify(stats)
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response

        except Exception as e:
            return jsonify({
                'error': str(e)
            }), 500

    @app.route('/api/parse-passage', methods=['POST', 'OPTIONS'])
    def api_parse_passage():
        """Parallel passage analysis — analyzes all words in a passage concurrently."""
        if request.method == 'OPTIONS':
            response = jsonify({'status': 'ok'})
            response.headers.add('Access-Control-Allow-Origin', '*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
            response.headers.add('Access-Control-Allow-Methods', 'POST')
            return response

        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
        if not data:
            data = request.form.to_dict()

        passage = data.get('passage', '').strip()
        if not passage:
            return jsonify({'success': False, 'error': 'Please provide a passage'}), 400

        try:
            result = parser.parse_passage(passage)
            response = jsonify(result)
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response
        except Exception as e:
            return jsonify({'success': False, 'error': f'Passage analysis error: {str(e)}'}), 500

    @app.route('/api/status', methods=['GET'])
    def api_status():
        """Database and parser status endpoint"""
        turso_ok = bool(parser.turso_db and parser.turso_db.connected)
        response = jsonify({
            'data_source': parser.data_source,
            'turso_connected': turso_ok,
            'verb_roots_loaded': len(parser.verb_roots),
            'dictionary_loaded': parser.dictionary is not None,
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response

if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        # CLI mode
        word = sys.argv[1]
        result = parser.parse(word)

        if result['success']:
            print(f"\n=== Analysis for: {result['original_form']} ===")
            print(f"Harvard-Kyoto: {result['hk_form']}")
            print(f"Script: {result['script']}")
            print(f"\nFound {result['total_found']} possible analyses (showing top {len(result['analyses'])}):\n")

            for i, analysis in enumerate(result['analyses'], 1):
                print(f"\n--- Analysis {i} (confidence: {analysis['confidence']:.2f}) ---")
                print(f"Type: {analysis.get('type', 'unknown')}")

                if analysis.get('type') == 'noun':
                    print(f"Stem: {analysis.get('stem', 'unknown')}")
                    print(f"Suffix: {analysis.get('suffix', 'unknown')}")
                    print(f"Gender: {analysis.get('gender', 'unknown')}")
                    print(f"Case: {analysis.get('case', 'unknown')}")
                    print(f"Number: {analysis.get('number', 'unknown')}")
                elif analysis.get('type') == 'verb':
                    print(f"Root: {analysis.get('root', 'unknown')}")
                    print(f"Ending: {analysis.get('ending', 'unknown')}")
                    print(f"Tense: {analysis.get('tense', 'unknown')}")
                    print(f"Person: {analysis.get('person', 'unknown')}")
                    print(f"Number: {analysis.get('number', 'unknown')}")

                print(f"Source: {analysis.get('source', 'unknown')}")
                if analysis.get('notes'):
                    print(f"Notes: {'; '.join(analysis['notes'])}")
        else:
            print(f"\nError: {result.get('error')}")
            if result.get('suggestions'):
                print("\nSuggestions:")
                for suggestion in result['suggestions']:
                    print(f"  - {suggestion}")

        sys.exit(0 if result['success'] else 1)
    else:
        # Server mode
        if not HAS_FLASK:
            print("Error: Flask is not installed. Install with: pip install flask")
            print("For CLI usage, provide a word as argument: python unified_parser.py <word>")
            sys.exit(1)

        port = int(os.environ.get("PORT", 5000))
        app.run(host='0.0.0.0', port=port, debug=True)
