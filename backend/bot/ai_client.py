import os
import re
import requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "meta-llama/llama-3-8b-instruct:free")

_knowledge_cache = None
_knowledge_blocks_cache = None


def load_knowledge():
    global _knowledge_cache
    try:
        with open("knowledge.txt", "r", encoding="utf-8") as f:
            _knowledge_cache = f.read()
            print(f"Knowledge loaded: {len(_knowledge_cache)} chars")
    except FileNotFoundError:
        print("knowledge.txt not found — AI will have no context")
        _knowledge_cache = ""
    except Exception as e:
        print(f"Failed to load knowledge: {e}")
        _knowledge_cache = ""
    return _knowledge_cache


def reload_knowledge():
    global _knowledge_cache, _knowledge_blocks_cache
    _knowledge_cache = None
    _knowledge_blocks_cache = None  # force re-splitting into blocks too
    return load_knowledge()


def get_knowledge():
    global _knowledge_cache
    if _knowledge_cache is None:
        load_knowledge()
    return _knowledge_cache


# Common words that appear in nearly every entry of this knowledge base
# ("cost", "timeline", "required", "documents"...) or in nearly any
# customer message ("what", "how", "need"...). Matching on these alone
# tells you almost nothing about which specific entry the customer is
# asking about, and lets them crowd out the words that actually do —
# e.g. "NTN", "trademark", "khula", "custody".
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "do", "does", "did",
    "i", "you", "we", "they", "it", "this", "that", "for", "and", "or",
    "of", "to", "in", "on", "at", "my", "your", "our", "what", "how",
    "when", "where", "why", "which", "can", "could", "would", "should",
    "will", "need", "needed", "needs", "want", "wanted", "please",
    "hi", "hello", "hey", "ok", "okay", "cost", "timeline", "case",
    "vary", "varies", "procedure", "required", "requirements", "documents", "document",
    "contact", "services", "service", "may", "also", "about", "tell",
    "me", "know", "get", "have", "has", "had", "with", "from", "if",
    "not", "no", "yes", "thanks", "thank", "us", "be", "been", "being",
    "some", "any", "all", "just", "like",
}


_SECTION_HEADER_RE = re.compile(r"^-{2,}.*-{2,}$")


def _split_knowledge_blocks(knowledge: str):
    """Split the knowledge base into whole logical entries — separated by
    blank lines, matching how knowledge.txt is actually written (a
    heading followed by its Required Documents / Cost / Timeline lines,
    then a blank line before the next entry) — instead of treating each
    line as an independent, context-free unit.

    knowledge.txt also uses standalone "--- SECTION NAME ---" header
    lines as their own blank-line-separated block, immediately followed
    by the actual content block. Left alone, a query matching only the
    section name (e.g. "khula") would retrieve just that bare header and
    miss the content — while unrelated blocks that happen to share a
    generic label word ("Procedure:", "Timeline:") would score just as
    well. Merging each header into the block right after it fixes both:
    the header's distinctive keyword now travels with its real content.
    """
    raw_blocks = [b.strip() for b in re.split(r"\n\s*\n", knowledge) if b.strip()]
    merged = []
    i = 0
    while i < len(raw_blocks):
        block = raw_blocks[i]
        if _SECTION_HEADER_RE.match(block) and i + 1 < len(raw_blocks):
            merged.append(block + "\n\n" + raw_blocks[i + 1])
            i += 2
        else:
            merged.append(block)
            i += 1
    return merged


def _get_knowledge_blocks():
    global _knowledge_blocks_cache
    if _knowledge_blocks_cache is None:
        _knowledge_blocks_cache = _split_knowledge_blocks(get_knowledge())
    return _knowledge_blocks_cache


def get_relevant_knowledge(msg: str, max_chars: int = 1600, max_blocks: int = 5) -> str:
    knowledge = get_knowledge()
    if not knowledge:
        return ""

    raw_words = re.findall(r"[a-zA-Z0-9]+", msg.lower())
    significant_words = [w for w in raw_words if w not in _STOPWORDS and len(w) > 2]
    if not significant_words:
        return ""

    blocks = _get_knowledge_blocks()
    scored = []
    for block in blocks:
        block_lower = block.lower()
        distinct_matches = 0
        total_occurrences = 0
        for w in set(significant_words):
            count = block_lower.count(w)
            if count:
                distinct_matches += 1
                total_occurrences += count
        if distinct_matches:
            # Distinct matched words matter far more than raw repetition —
            # otherwise a block that just repeats one common-ish word
            # ("procedure", "timeline") several times can outrank, or tie
            # with, the block that actually matches several of the
            # customer's specific query words.
            score = distinct_matches * 10 + total_occurrences
            scored.append((score, block))

    if not scored:
        return ""

    # Highest-scoring entries first, kept whole (not cut off mid-block),
    # up to a char budget generous enough to include the full
    # Required Documents / Cost / Timeline for a few matching services.
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = []
    total_len = 0
    for score, block in scored[:max_blocks]:
        if selected and total_len + len(block) > max_chars:
            break
        selected.append(block)
        total_len += len(block)

    return "\n\n".join(selected)


def ask_ai(user_message: str, retries: int = 1) -> str:
    if not OPENROUTER_API_KEY:
        return "AI service is not configured. Please contact support."

    context = get_relevant_knowledge(user_message)
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    system_prompt = f"""You are a professional legal assistant for LawAdvise Consulting And BizAdvise, a Pakistani law firm.

RULES:
- Reply in 2-3 short, clear sentences
- Be polite, professional, and empathetic at all times
- Answer based strictly on the knowledge base provided
- If the question is not covered in the knowledge base, say: "For this matter, I recommend speaking directly with one of our legal experts who can assist you better."
- Never give specific legal advice, case predictions, or legal opinions
- If the user writes in Urdu, reply in Urdu. If in English, reply in English.
- If a user wants to book a consultation or talk to a lawyer, tell them our team will be in touch shortly
- Do NOT add safety ratings, labels, or metadata to your reply

KNOWLEDGE BASE:
{context}"""
    
    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }

    for attempt in range(retries + 1):
        try:
            res = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=15,
            )
            data = res.json()

            if "choices" in data:
                reply = (data["choices"][0].get("message", {}) or {}).get("content", "") or ""
                cleaned = _clean_reply(reply)
                if not cleaned:
                    # Model returned nothing usable — empty content, or a
                    # response that was ONLY metadata lines that _clean_reply
                    # stripped out. Sending "" to WhatsApp either fails the
                    # API call or shows an empty bubble, so fall back instead.
                    print(f"AI returned empty/unusable reply, raw content: {reply!r}")
                    return FALLBACK_REPLY
                return cleaned

            print(f"AI unexpected response: {data}")
            return FALLBACK_REPLY

        except requests.Timeout:
            print(f"AI timeout (attempt {attempt + 1})")
            if attempt < retries:
                continue
            return "Server is busy. Please try again in a moment."
        except Exception as e:
            print(f"ask_ai error (attempt {attempt + 1}): {e}")
            if attempt < retries:
                continue
            return "Server error. Please try again."

    return "Server error. Please try again."


FALLBACK_REPLY = (
    "For this matter, I recommend speaking directly with one of our "
    "legal experts who can assist you better."
)


def _clean_reply(text: str) -> str:
    """Remove metadata lines that some models append to responses."""
    if not text or not text.strip():
        return ""
    lines = text.strip().split("\n")
    clean_lines = []
    skip_prefixes = (
        "user safety:",
        "content safety:",
        "safe:",
        "unsafe:",
        "safety:",
        "classification:",
        "content:",
        "note:",
        "disclaimer:",
    )
    for line in lines:
        if line.strip().lower().startswith(skip_prefixes):
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines).strip()