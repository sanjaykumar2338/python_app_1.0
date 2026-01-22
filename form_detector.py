from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

from extractor_base import normalize_text


class FormType(str, Enum):
    FORM_A = "FORM_A"
    FORM_B = "FORM_B"
    FORM_C = "FORM_C"
    FORM_D = "FORM_D"
    FORM_ADMIN = "FORM_ADMIN"
    UNKNOWN = "UNKNOWN"


@dataclass
class DetectionResult:
    form_type: FormType
    confidence: float
    matched_markers: List[str]

    def to_dict(self) -> Dict:
        return {
            "form_type": self.form_type.value,
            "confidence_score": round(self.confidence, 3),
            "matched_markers": self.matched_markers,
        }


FORM_MARKERS: Dict[FormType, Dict[str, int]] = {
    FormType.FORM_A: {
        "surrogate's court": 2,
        "administration petition": 3,
        "administration proceeding": 2,
        "file no.": 1,
        "state of new york": 1,
        "county of richmond": 3,
        "staten island": 3,
        "domicile": 1,
        "improved real property": 1,
    },
    FormType.FORM_B: {
        "probate petition": 3,
        "letters testamentary": 2,
        "citations": 1,
        "kings county": 2,
        "queens county": 2,
        "surrogate court of": 1,
        "telephone number": 1,
    },
    FormType.FORM_C: {
        "affidavit of heirship": 3,
        "family tree": 2,
        "renunciation": 2,
        "waiver of process": 2,
        "distributee": 2,
        "relationship to decedent": 1,
    },
    FormType.FORM_D: {
        "voluntary administration": 3,
        "small estate": 3,
        "public administrator": 2,
        "carolyn rubio diaz": 4,
        "surrogate's court richmond county": 3,
        "docket number": 1,
    },
    FormType.FORM_ADMIN: {
        "petition for letters of administration": 4,
        "petition for letters of": 3,
        "administration proceeding": 3,
        "form a-1": 3,
        "a1 (03/18)": 3,
        "petitioner information": 2,
        "decedent information": 2,
        "surrogate's court of the state of new york": 1,
    },
}


def _score_form(text: str, markers: Dict[str, int]) -> (int, List[str]):
    matched = []
    score = 0
    for marker, weight in markers.items():
        if marker.lower() in text:
            matched.append(marker)
            score += weight
    return score, matched


def detect_form(text: str, first_page_hint: str = "") -> DetectionResult:
    normalized = normalize_text(text)
    combined = f"{normalized}\n{first_page_hint}".lower()
    if "petition for letters of" in combined and (
        "administration proceeding" in combined or "form a-1" in combined or "a1 (03/18)" in combined
    ):
        return DetectionResult(FormType.FORM_ADMIN, 1.0, ["petition for letters of", "administration proceeding"])
    best: DetectionResult = DetectionResult(FormType.UNKNOWN, 0.0, [])

    for form_type, markers in FORM_MARKERS.items():
        score, matched = _score_form(combined, markers)
        max_score = sum(abs(weight) for weight in markers.values()) or 1
        confidence = score / max_score
        if confidence > best.confidence or (confidence == best.confidence and len(matched) > len(best.matched_markers)):
            best = DetectionResult(form_type, confidence, matched)

    if best.confidence <= 0:
        return DetectionResult(FormType.UNKNOWN, 0.0, [])
    return best
