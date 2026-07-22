import re

SUSPICIOUS_PATTERNS = [
    r"\bkeylogger\b",
    r"\bransomware\b",
    r"\bbackdoor\b",
    r"\breverse\s+shell\b",
    r"\bspyware\b",
    r"\bmalware\b",
    r"\bexploit\s+code\b",
    r"\bcryptojacker\b",
    r"\brootkit\b",
    r"\bcred\s+stealer\b",
    r"\bcredential\s+stealer\b",
    r"\bwiper\s+malware\b",
    r"\bwindows\s+defender\s+bypass\b",
    r"\bdishonest\s+activity\b",
]

def check_moderation(text: str) -> tuple[bool, str]:
    """
    Check if a text contains potential security-risk keywords (malware/exploit terms).
    Returns (is_flagged, matched_reason).
    """
    if not text:
        return False, ""
    
    lower_text = text.lower()
    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, lower_text):
            match_word = pattern.replace(r"\b", "").replace(r"\s+", " ")
            return True, f"contains terms related to potential security risks (e.g., '{match_word}')"
            
    return False, ""
