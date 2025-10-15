import json
import string
import re
from difflib import SequenceMatcher


# ---------------- Basic Helpers ----------------
def tokenize(text):
    text = text.lower()
    return re.findall(r'\b\w+\b', text)


def expand_tokens(tokens):
    synonym_map = {
        "dob": ["date of birth", "birth", "born", "birthday"],
        "birth": ["dob", "date of birth", "born", "birthday"],
        "born": ["dob", "birth", "date of birth", "birthday"],
        "wife": ["spouse", "partner"],
        "husband": ["spouse", "partner"],
        "money": ["worth", "income", "salary", "wealth"],
        "runs": ["score", "scored", "innings"],
        "value": ["worth", "valuation", "net worth"],
        "brand": ["company", "business"]
    }
    expanded = set(tokens)
    for tok in tokens:
        if tok in synonym_map:
            expanded.update(synonym_map[tok])
    return list(expanded)


def fuzzy_ratio(a, b):
    # Ensure both are strings
    if not isinstance(a, str):
        a = str(a)
    if not isinstance(b, str):
        b = str(b)
    try:
        return SequenceMatcher(None, a, b).ratio()
    except Exception:
        return 0



# ---------------- NLP CLASS ----------------
class NLP:
    def __init__(self, memo):
        if not isinstance(memo, dict):
            raise TypeError("memo must be a dictionary")
        self.memo = memo

    # ✂️ Clean + Split text
    def tokenize(self, text):
        if not isinstance(text, str):
            raise TypeError("Input text must be a string")

        stopwords = ["ing", "ly", "!", ".", "ed", "es", "-",'is','who','what']
        tokens = []
        for token in text.split():
            word = token.lower()
            word = word.translate(str.maketrans('', '', string.punctuation))
            # Remove suffixes
            for suf in ["ing", "ly", "ed", "es"]:
                if word.endswith(suf) and len(word) > len(suf) + 2:
                    word = word[:-len(suf)]
                    break

            # Remove common question words completely
            if word in ["is", "are", "was", "were", "why", "how"]:
                continue

            word = word.strip()
            if word:
                tokens.append(word)
        return tokens

    # 🔍 Recursive deep search for keyword presence
    def deep_search(self, data, word, path=None):
        if path is None:
            path = []
        if isinstance(data, dict):
            for k, v in data.items():
                new_path = path + [k]
                if isinstance(v, str) and fuzzy_ratio(word, v) > 0.8:
                    return (".".join(new_path), word)
                elif isinstance(v, list):
                    for x in v:
                        if isinstance(x, str) and fuzzy_ratio(word, x) > 0.8:
                            return (".".join(new_path), word)
                elif isinstance(v, dict):
                    res = self.deep_search(v, word, new_path)
                    if res:
                        return res
        elif isinstance(data, list):
            for i, item in enumerate(data):
                res = self.deep_search(item, word, path + [f"[{i}]"])
                if res:
                    return res
        return None

    # 🧠 Detect direct commands
    def detect_commands(self, tokens):
        command, unfound = {}, []
        for word in tokens:
            found = self.deep_search(self.memo, word)
            if found:
                key_path, matched_word = found
                command[key_path] = matched_word
            else:
                unfound.append(word)
        return command, unfound

    # 🌐 Smart full JSON search (semantic aware)
    def smart_search(self, query, data):
        tokens = expand_tokens(tokenize(query))
        matches = self._search_json(data, tokens)
        scored = [(self._score_match(val, tokens, path), path, val) for path, val in matches]
        scored.sort(reverse=True, key=lambda x: x[0])

        # Ignore weak matches
        THRESHOLD = 3.0
        strong_matches = [(p, v) for s, p, v in scored if s >= THRESHOLD]

        if not strong_matches:
            return [("not in memory", None)]
        return strong_matches


    # 📦 Extract entity names (like person names)
    def _extract_entities(self, data):
        people = []
        if "info" in data and "persons" in data["info"]:
            people = [p.lower() for p in data["info"]["persons"].keys()]
        return people

    # 🧩 Deep recursive JSON walker
    def _search_json(self, d, tokens, focus_entity=None, path=""):
        results = []
        if isinstance(d, dict):
            for k, v in d.items():
                new_path = f"{path} → {k}" if path else k
                if focus_entity and focus_entity not in new_path.lower():
                    # skip irrelevant person sections
                    if "persons" in new_path.lower() and focus_entity not in new_path.lower():
                        continue
                key_tokens = tokenize(k)
                if any(any(fuzzy_ratio(tok, ktok) > 0.8 for ktok in key_tokens) for tok in tokens):
                    results.append((new_path, v))
                results.extend(self._search_json(v, tokens, focus_entity, new_path))
        elif isinstance(d, list):
            for i, item in enumerate(d):
                results.extend(self._search_json(item, tokens, focus_entity, f"{path}[{i}]"))
        elif isinstance(d, str):
            val_tokens = tokenize(d)
            if any(any(fuzzy_ratio(tok, vt) > 0.8 for vt in val_tokens) for tok in tokens):
                results.append((path, d))
        return results

    # ⚖️ Smart context scoring
    def _score_match(self, val, tokens, path=""):
    # Make searchable text
        if isinstance(val, str):
            val_str = val.lower()
        elif isinstance(val, list):
            val_str = " ".join(str(v).lower() for v in val)
        elif isinstance(val, dict):
            val_str = " ".join(str(v).lower() for v in val.values())
        else:
            val_str = str(val).lower()

        combined = path.lower() + " " + val_str

        # 1️⃣ Token overlap
        overlap = sum(1 for t in tokens if t in combined)

        # 2️⃣ Fuzzy ratio (ignore weak partial matches)
        fuzzy_scores = [fuzzy_ratio(t, combined) for t in tokens]
        strong_fuzzy = [f for f in fuzzy_scores if f > 0.7]
        fuzzy_avg = sum(strong_fuzzy) / len(strong_fuzzy) if strong_fuzzy else 0

        # 3️⃣ Token proximity (closer tokens mean better relevance)
        positions = [combined.find(t) for t in tokens if t in combined]
        proximity = 0
        if len(positions) > 1:
            distances = [abs(positions[i] - positions[i - 1]) for i in range(1, len(positions))]
            avg = sum(distances) / len(distances)
            proximity = max(0, 10 - avg / 40)

        # 4️⃣ Length penalty (too long text is likely generic/irrelevant)
        length_score = max(0, 3 - len(val_str) / 150)

        # 5️⃣ Penalize unrelated contexts (e.g., if token is not present even once)
        if overlap == 0 and fuzzy_avg < 0.5:
            return 0  # totally irrelevant

        # 6️⃣ Final weighted score
        score = (overlap * 3.5) + (fuzzy_avg * 5) + proximity + length_score
        
        return round(score, 2)

