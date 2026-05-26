"""
Prakrit Dictionary Lookup Module

Provides efficient dictionary lookup functionality using SQLite database.
Integrates with unified_parser.py to add meanings to morphological analyses.

Usage:
    from dictionary_lookup import PrakritDictionary

    dict = PrakritDictionary('prakrit_dict.db')
    meanings = dict.lookup('ghāya')
"""

import sqlite3
import json
from typing import List, Dict, Optional, Tuple
import os


class PrakritDictionary:
    """SQLite-based Prakrit dictionary lookup"""

    def __init__(self, db_path: str):
        """
        Initialize dictionary

        Args:
            db_path: Path to SQLite database file
        """
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Dictionary database not found: {db_path}")

        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()

    def __del__(self):
        """Close database connection"""
        if hasattr(self, 'conn'):
            self.conn.close()

    def lookup(self, word: str, script: str = 'HK') -> List[Dict]:
        """
        Look up a word in the dictionary

        Args:
            word: Word to look up (in HK transliteration or Devanagari)
            script: 'HK' or 'Devanagari'

        Returns:
            List of dictionary entries
        """
        if script == 'HK':
            field = 'headword_translit'
        else:
            field = 'headword_devanagari'

        query = f'''
            SELECT
                headword_devanagari,
                headword_translit,
                type_list,
                gender,
                sanskrit_equivalent,
                is_desya,
                is_root,
                is_word,
                meanings,
                references,
                cross_references
            FROM dictionary
            WHERE {field} = ?
        '''

        self.cursor.execute(query, (word,))
        results = self.cursor.fetchall()

        entries = []
        for row in results:
            entry = {
                'headword_devanagari': row[0],
                'headword_translit': row[1],
                'type': json.loads(row[2]) if row[2] else [],
                'gender': row[3],
                'sanskrit_equivalent': json.loads(row[4]) if row[4] else [],
                'is_desya': bool(row[5]),
                'is_root': bool(row[6]),
                'is_word': bool(row[7]),
                'meanings': json.loads(row[8]) if row[8] else [],
                'references': json.loads(row[9]) if row[9] else [],
                'cross_references': json.loads(row[10]) if row[10] else []
            }
            entries.append(entry)

        return entries

    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Full-text search in dictionary

        Args:
            query: Search query
            limit: Maximum number of results

        Returns:
            List of matching entries
        """
        sql = '''
            SELECT
                d.headword_devanagari,
                d.headword_translit,
                d.type_list,
                d.meanings
            FROM dictionary_fts fts
            JOIN dictionary d ON fts.rowid = d.id
            WHERE dictionary_fts MATCH ?
            LIMIT ?
        '''

        self.cursor.execute(sql, (query, limit))
        results = self.cursor.fetchall()

        entries = []
        for row in results:
            entry = {
                'headword_devanagari': row[0],
                'headword_translit': row[1],
                'type': json.loads(row[2]) if row[2] else [],
                'meanings': json.loads(row[3]) if row[3] else []
            }
            entries.append(entry)

        return entries

    def lookup_root(self, root: str) -> List[Dict]:
        """
        Look up entries for a specific root

        Args:
            root: Root form (verb/noun root)

        Returns:
            List of entries where this is marked as a root
        """
        query = '''
            SELECT
                headword_devanagari,
                headword_translit,
                type_list,
                meanings,
                sanskrit_equivalent
            FROM dictionary
            WHERE headword_translit = ? AND is_root = 1
        '''

        self.cursor.execute(query, (root,))
        results = self.cursor.fetchall()

        entries = []
        for row in results:
            entry = {
                'headword_devanagari': row[0],
                'headword_translit': row[1],
                'type': json.loads(row[2]) if row[2] else [],
                'meanings': json.loads(row[3]) if row[3] else [],
                'sanskrit_equivalent': json.loads(row[4]) if row[4] else []
            }
            entries.append(entry)

        return entries

    def get_definitions(self, word: str, script: str = 'HK', max_senses: int = 3) -> List[str]:
        """
        Get simplified list of definitions for a word

        Args:
            word: Word to look up
            script: 'HK' or 'Devanagari'
            max_senses: Maximum number of senses to return

        Returns:
            List of definition strings
        """
        entries = self.lookup(word, script)

        definitions = []
        for entry in entries:
            for meaning in entry.get('meanings', [])[:max_senses]:
                definition = meaning.get('definition', '')
                if definition:
                    definitions.append(definition)

        return definitions

    def get_stats(self) -> Dict:
        """Get dictionary statistics"""
        stats = {}

        # Total entries
        self.cursor.execute('SELECT COUNT(*) FROM dictionary')
        stats['total_entries'] = self.cursor.fetchone()[0]

        # Words vs roots
        self.cursor.execute('SELECT COUNT(*) FROM dictionary WHERE is_word = 1')
        stats['total_words'] = self.cursor.fetchone()[0]

        self.cursor.execute('SELECT COUNT(*) FROM dictionary WHERE is_root = 1')
        stats['total_roots'] = self.cursor.fetchone()[0]

        # Desya words
        self.cursor.execute('SELECT COUNT(*) FROM dictionary WHERE is_desya = 1')
        stats['desya_words'] = self.cursor.fetchone()[0]

        return stats


def integrate_with_parser_analysis(analysis: Dict, dictionary: PrakritDictionary) -> Dict:
    """
    Add dictionary meanings to a parser analysis

    Args:
        analysis: Analysis dict from unified_parser
        dictionary: PrakritDictionary instance

    Returns:
        Analysis with meanings added
    """
    # Determine what to look up
    if analysis.get('type') == 'noun':
        lookup_word = analysis.get('stem')
    elif analysis.get('type') == 'verb':
        lookup_word = analysis.get('root')
    else:
        return analysis

    if not lookup_word:
        return analysis

    # Look up in dictionary
    entries = dictionary.lookup(lookup_word, script='HK')

    if entries:
        # Add meanings from first entry
        entry = entries[0]
        analysis['dictionary'] = {
            'headword_devanagari': entry['headword_devanagari'],
            'sanskrit_equivalent': entry.get('sanskrit_equivalent', []),
            'meanings': [m.get('definition', '') for m in entry.get('meanings', [])[:3]],
            'is_desya': entry.get('is_desya', False)
        }

    return analysis


# Example usage
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 dictionary_lookup.py <database.db> [word]")
        sys.exit(1)

    db_path = sys.argv[1]
    test_word = sys.argv[2] if len(sys.argv) > 2 else 'ghāya'

    print(f"Opening dictionary: {db_path}")
    dictionary = PrakritDictionary(db_path)

    # Show stats
    stats = dictionary.get_stats()
    print(f"\nDictionary Statistics:")
    print(f"  Total entries: {stats['total_entries']}")
    print(f"  Words: {stats['total_words']}")
    print(f"  Roots: {stats['total_roots']}")
    print(f"  Desya words: {stats['desya_words']}")

    # Test lookup
    print(f"\n--- Looking up: {test_word} ---")
    entries = dictionary.lookup(test_word)

    if entries:
        for i, entry in enumerate(entries, 1):
            print(f"\nEntry {i}:")
            print(f"  Devanagari: {entry['headword_devanagari']}")
            print(f"  Transliteration: {entry['headword_translit']}")
            print(f"  Type: {', '.join(entry['type'])}")
            if entry['sanskrit_equivalent']:
                print(f"  Sanskrit: {', '.join(entry['sanskrit_equivalent'])}")
            if entry['is_desya']:
                print(f"  [Desya word]")
            if entry['is_root']:
                print(f"  [Root form]")

            print(f"  Meanings:")
            for meaning in entry['meanings'][:5]:
                sense_num = meaning.get('sense_number', '?')
                definition = meaning.get('definition', 'N/A')
                print(f"    {sense_num}. {definition}")
    else:
        print("  No entries found")

    # Test search
    print(f"\n--- Searching for: {test_word} ---")
    search_results = dictionary.search(test_word, limit=5)

    if search_results:
        print(f"Found {len(search_results)} matches:")
        for result in search_results:
            print(f"  - {result['headword_translit']} ({result['headword_devanagari']})")
    else:
        print("  No search results")
