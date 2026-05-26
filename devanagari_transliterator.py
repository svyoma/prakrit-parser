"""
Simple Devanagari to Harvard-Kyoto transliterator
"""

# Devanagari vowels to HK
VOWELS = {
    'अ': 'a', 'आ': 'A', 'इ': 'i', 'ई': 'I', 'उ': 'u', 'ऊ': 'U',
    'ऋ': 'R', 'ॠ': 'RR', 'ऌ': 'lR', 'ॡ': 'lRR',
    'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au'
}

# Devanagari vowel signs (mātrā) to HK
VOWEL_SIGNS = {
    'ा': 'A', 'ि': 'i', 'ी': 'I', 'ु': 'u', 'ू': 'U',
    'ृ': 'R', 'ॄ': 'RR', 'ॢ': 'lR', 'ॣ': 'lRR',
    'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au'
}

# Devanagari consonants to HK
CONSONANTS = {
    # Velars
    'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'G',
    # Palatals
    'च': 'c', 'छ': 'ch', 'ज': 'j', 'झ': 'jh', 'ञ': 'J',
    # Retroflexes
    'ट': 'T', 'ठ': 'Th', 'ड': 'D', 'ढ': 'Dh', 'ण': 'N',
    # Dentals
    'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
    # Labials
    'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm',
    # Semivowels
    'य': 'y', 'र': 'r', 'ल': 'l', 'ळ': 'L', 'व': 'v',
    # Sibilants
    'श': 'z', 'ष': 'S', 'स': 's',
    # Aspirate
    'ह': 'h'
}

# Special characters
SPECIAL = {
    'ं': 'M',   # Anusvara
    'ः': 'H',   # Visarga
    'ँ': '~',   # Candrabindu
    'ऽ': "'",   # Avagraha
    '्': ''     # Halanta/Virama (removes inherent 'a')
}

# Digits
DIGITS = {
    '०': '0', '१': '1', '२': '2', '३': '3', '४': '4',
    '५': '5', '६': '6', '७': '7', '८': '8', '९': '9'
}

def devanagari_to_hk(text: str) -> str:
    """
    Convert Devanagari text to Harvard-Kyoto transliteration

    Args:
        text: Devanagari text

    Returns:
        Harvard-Kyoto transliteration
    """
    result = []
    i = 0

    while i < len(text):
        char = text[i]

        # Skip whitespace and punctuation
        if char in ' \t\n.,;:!?()-[]{}':
            result.append(char)
            i += 1
            continue

        # Check for standalone vowels
        if char in VOWELS:
            result.append(VOWELS[char])
            i += 1
            continue

        # Check for consonants
        if char in CONSONANTS:
            result.append(CONSONANTS[char])

            # Check for following vowel sign
            if i + 1 < len(text):
                next_char = text[i + 1]

                # Halanta (virama) - no vowel
                if next_char == '्':
                    i += 2  # Skip both consonant and virama
                    continue

                # Vowel sign
                elif next_char in VOWEL_SIGNS:
                    result.append(VOWEL_SIGNS[next_char])
                    i += 2  # Skip both consonant and vowel sign
                    continue

                # Anusvara, Visarga, Candrabindu
                elif next_char in SPECIAL:
                    result.append('a')  # Inherent 'a'
                    result.append(SPECIAL[next_char])
                    i += 2
                    continue

            # No following vowel sign = inherent 'a'
            result.append('a')
            i += 1
            continue

        # Special characters (anusvara, visarga, etc.)
        if char in SPECIAL:
            result.append(SPECIAL[char])
            i += 1
            continue

        # Digits
        if char in DIGITS:
            result.append(DIGITS[char])
            i += 1
            continue

        # Unknown character - skip
        i += 1

    return ''.join(result)

def test_transliteration():
    """Test cases for transliteration"""
    test_cases = [
        ('पुच्छिस्संति', 'pucchissaMti'),
        ('मुणिन्ति', 'muNinti'),
        ('जाणिन्ति', 'jANinti'),
        ('मुणीहिंतो', 'muNIhiMto'),
        ('नेमो', 'nemo'),
        ('भवति', 'bhavati'),
    ]

    print("Testing Devanagari to HK transliteration:")
    print("=" * 60)
    for dev, expected in test_cases:
        result = devanagari_to_hk(dev)
        status = "✓" if result == expected else "✗"
        print(f"{status} {dev:15s} → {result:15s} (expected: {expected})")

if __name__ == '__main__':
    test_transliteration()
