"""MITRE ATT&CK technique mapping for KGCP triplets."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..models import Triplet

logger = logging.getLogger(__name__)

ATTACK_DATA_URL = (
    "https://raw.githubusercontent.com/mitre/cti/master/"
    "enterprise-attack/enterprise-attack.json"
)
DEFAULT_CACHE_PATH = Path("~/.kgcp/enterprise-attack.json").expanduser()

_STOPWORDS = frozenset({
    "the", "and", "for", "that", "this", "with", "from", "have", "been",
    "were", "are", "was", "can", "may", "use", "used", "using", "also",
    "which", "their", "them", "they", "will", "other", "more", "than",
    "into", "over", "such", "through", "about", "between",
})


@dataclass
class AttackMatch:
    """A matched ATT&CK technique."""

    technique_id: str
    technique_name: str
    match_confidence: float
    matched_on: str
    tactic: str = ""


class AttackMapper:
    """Maps KGCP triplets to MITRE ATT&CK techniques."""

    def __init__(self, cache_path: Path | None = None):
        self.cache_path = cache_path or DEFAULT_CACHE_PATH
        self._techniques: list[dict] = []
        self._keyword_index: dict[str, list[dict]] = {}
        self._loaded = False

    def ensure_data(self, force_download: bool = False) -> None:
        """Load ATT&CK data, downloading if needed."""
        if self._loaded and not force_download:
            return
        if not self.cache_path.exists() or force_download:
            self._download()
        self._load_from_cache()

    def _download(self) -> None:
        """Download ATT&CK STIX bundle from MITRE GitHub."""
        import requests

        logger.info("Downloading ATT&CK data from %s", ATTACK_DATA_URL)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(ATTACK_DATA_URL, timeout=60)
        resp.raise_for_status()
        self.cache_path.write_text(resp.text)
        logger.info("Saved ATT&CK data to %s", self.cache_path)

    def _load_from_cache(self) -> None:
        """Parse the STIX bundle and build keyword index."""
        raw = json.loads(self.cache_path.read_text())
        objects = raw.get("objects", [])

        self._techniques = []
        self._keyword_index = {}

        for obj in objects:
            if obj.get("type") != "attack-pattern":
                continue
            if obj.get("revoked") or obj.get("x_mitre_deprecated"):
                continue

            technique_id = ""
            for ref in obj.get("external_references", []):
                if ref.get("source_name") == "mitre-attack":
                    technique_id = ref.get("external_id", "")
                    break
            if not technique_id:
                continue

            tactic = ""
            for phase in obj.get("kill_chain_phases", []):
                if phase.get("kill_chain_name") == "mitre-attack":
                    tactic = phase.get("phase_name", "")
                    break

            name = obj.get("name", "")
            description = obj.get("description", "")

            tech = {
                "id": technique_id,
                "name": name,
                "tactic": tactic,
                "description": description[:500],
                "keywords": self._extract_keywords(name, description),
            }
            self._techniques.append(tech)

            for kw in tech["keywords"]:
                self._keyword_index.setdefault(kw, []).append(tech)

        self._loaded = True
        logger.info("Loaded %d ATT&CK techniques", len(self._techniques))

    @staticmethod
    def _extract_keywords(name: str, description: str) -> set[str]:
        """Extract searchable keywords from technique name and description."""
        words: set[str] = set()
        for w in re.findall(r"[a-z]{3,}", name.lower()):
            words.add(w)
        first_sentence = description.split(".")[0] if description else ""
        for w in re.findall(r"[a-z]{4,}", first_sentence.lower()):
            words.add(w)
        words -= _STOPWORDS
        return words

    def match_triplet(
        self,
        subject: str,
        predicate: str,
        obj: str,
        entity_type: str = "",
        max_results: int = 5,
    ) -> list[AttackMatch]:
        """Match a single triplet against ATT&CK techniques.

        Returns ranked list, highest confidence first.
        """
        self.ensure_data()
        candidates: dict[str, AttackMatch] = {}

        pred_words = set(re.findall(r"[a-z]{3,}", predicate.lower()))
        obj_words = set(re.findall(r"[a-z]{3,}", obj.lower()))
        subj_words = set(re.findall(r"[a-z]{3,}", subject.lower()))

        for tech in self._techniques:
            score = 0.0
            matched_on: list[str] = []
            tech_name_lower = tech["name"].lower()

            # Direct name match (highest confidence)
            if tech_name_lower in predicate.lower() or tech_name_lower in obj.lower():
                score += 0.6
                matched_on.append(f"name:{tech['name']}")

            # Keyword overlap with predicate
            pred_overlap = pred_words & tech["keywords"]
            if pred_overlap:
                score += 0.3 * (len(pred_overlap) / max(len(pred_words), 1))
                matched_on.append(f"predicate:{','.join(sorted(pred_overlap))}")

            # Keyword overlap with object
            obj_overlap = obj_words & tech["keywords"]
            if obj_overlap:
                score += 0.2 * (len(obj_overlap) / max(len(obj_words), 1))
                matched_on.append(f"object:{','.join(sorted(obj_overlap))}")

            # Keyword overlap with subject
            subj_overlap = subj_words & tech["keywords"]
            if subj_overlap:
                score += 0.1 * (len(subj_overlap) / max(len(subj_words), 1))
                matched_on.append(f"subject:{','.join(sorted(subj_overlap))}")

            # Bonus for entity typed as "technique"
            if entity_type == "technique":
                score += 0.1

            if score > 0.1:
                match = AttackMatch(
                    technique_id=tech["id"],
                    technique_name=tech["name"],
                    match_confidence=min(1.0, score),
                    matched_on="; ".join(matched_on),
                    tactic=tech["tactic"],
                )
                existing = candidates.get(tech["id"])
                if existing is None or existing.match_confidence < score:
                    candidates[tech["id"]] = match

        results = sorted(
            candidates.values(), key=lambda m: m.match_confidence, reverse=True
        )
        return results[:max_results]

    def match_triplets(
        self, triplets: list[Triplet], max_results_per: int = 3
    ) -> dict[str, list[AttackMatch]]:
        """Match multiple triplets. Returns dict of triplet_id -> matches."""
        from ..extraction.confidence import infer_entity_type

        self.ensure_data()
        results: dict[str, list[AttackMatch]] = {}
        for t in triplets:
            entity_type = infer_entity_type(t.subject)
            matches = self.match_triplet(
                t.subject, t.predicate, t.object,
                entity_type=entity_type, max_results=max_results_per,
            )
            if matches:
                results[t.triplet_id] = matches
        return results
