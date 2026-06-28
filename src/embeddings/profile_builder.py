from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Shared defaults used when RedRob signals are unavailable.
DEFAULT_REDROB_SIGNALS = {
    "response_rate": 0.5,
    "interview_rate": 0.5,
    "offer_rate": 0.5,
}


# ---------------------------------------------------------------------------
# Candidate profile model
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class CandidateProfile:
    candidate_id: str
    headline: str = ""
    summary: str = ""
    current_title: str = ""
    skills: list[str] = field(default_factory=list)
    career_history: list[dict[str, Any]] = field(default_factory=list)
    total_experience_years: float = 0.0
    education: dict[str, Any] = field(default_factory=dict)
    redrob_signals: dict[str, Any] = field(default_factory=dict)
    profile_text: str = ""


# ---------------------------------------------------------------------------
# Data normalization helpers
# ---------------------------------------------------------------------------
def safe_get(data: Any, *keys: str, default: Any = None) -> Any:
    """Return the first present value from a sequence of candidate keys."""
    if not isinstance(data, Mapping):
        return default

    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def normalize_skills(skills_input: Any) -> list[str]:
    """Normalize raw skill values into a deduplicated list of strings."""
    if not skills_input:
        return []

    if isinstance(skills_input, str):
        return [skills_input.strip()] if skills_input.strip() else []

    if isinstance(skills_input, Mapping):
        skill_name = safe_get(skills_input, "name", "skill", "title", default="")
        return [str(skill_name).strip()] if str(skill_name).strip() else []

    if not isinstance(skills_input, Sequence) or isinstance(skills_input, (str, bytes, bytearray)):
        return []

    normalized: list[str] = []
    seen: set[str] = set()

    for item in skills_input:
        if isinstance(item, str):
            candidate = item.strip()
        elif isinstance(item, Mapping):
            candidate = safe_get(item, "name", "skill", "title", default="")
            candidate = str(candidate).strip() if candidate is not None else ""
        else:
            candidate = str(item).strip()

        if candidate and candidate.lower() not in seen:
            normalized.append(candidate)
            seen.add(candidate.lower())

    return normalized


def normalize_career_history(career_history_input: Any) -> list[dict[str, Any]]:
    """Normalize messy career history records into a consistent list of dicts."""
    if not career_history_input:
        return []

    if isinstance(career_history_input, Mapping):
        entries: Sequence[Any] = [career_history_input]
    elif isinstance(career_history_input, Sequence) and not isinstance(
        career_history_input, (str, bytes, bytearray)
    ):
        entries = career_history_input
    else:
        entries = [career_history_input]

    normalized: list[dict[str, Any]] = []

    for entry in entries:
        if not isinstance(entry, Mapping):
            continue

        cleaned: dict[str, Any] = {}
        title = safe_get(entry, "title", "role", "position", "job_title", default="")
        if title:
            cleaned["title"] = str(title).strip()

        company = safe_get(entry, "company", "employer", "organization", default="")
        if company:
            cleaned["company"] = str(company).strip()

        years = safe_get(entry, "years", "experience_years", default=None)
        if years is None:
            years = safe_get(entry, "duration_years", default=None)
        if years is not None:
            cleaned["years"] = years

        description = safe_get(entry, "description", "summary", default="")
        if description:
            cleaned["description"] = str(description).strip()

        if cleaned:
            normalized.append(cleaned)

    return normalized


def calculate_total_experience(
    career_history_input: Any,
    fallback_years: Any = None,
) -> float:
    """Calculate total experience from career history, ignoring invalid values."""
    total = 0.0
    normalized_history = normalize_career_history(career_history_input)

    for entry in normalized_history:
        years_value = safe_get(entry, "years", default=None)
        if years_value is None:
            continue

        numeric_value = _coerce_float(years_value)
        if numeric_value is not None:
            total += numeric_value

    if total > 0:
        return round(total, 2)

    if fallback_years is None:
        return 0.0

    numeric_value = _coerce_float(fallback_years)
    return round(numeric_value, 2) if numeric_value is not None else 0.0


def build_profile_text(
    headline: str,
    summary: str,
    current_title: str,
    skills: list[str],
    career_history: list[dict[str, Any]],
    education: Any,
) -> str:
    """Create a clean, human-readable profile paragraph from normalized fields."""
    parts: list[str] = []

    for value in (headline, summary):
        cleaned = _clean_text(value)
        if cleaned:
            parts.append(cleaned)

    if current_title:
        parts.append(f"Current title: {_clean_text(current_title)}")

    if skills:
        unique_skills = list(dict.fromkeys(skill for skill in skills if skill))
        parts.append(f"Skills: {', '.join(unique_skills)}")

    titles = []
    for entry in career_history:
        title = _clean_text(entry.get("title", ""))
        if title and title not in titles:
            titles.append(title)

    if titles:
        parts.append(f"Career history: {', '.join(titles)}")

    if isinstance(education, Mapping):
        education_bits: list[str] = []
        degree = safe_get(education, "degree", "qualification", default="")
        institution = safe_get(education, "institution", "school", "university", default="")
        field_of_study = safe_get(education, "field_of_study", "field", default="")

        if degree:
            education_bits.append(str(degree).strip())
        if field_of_study:
            education_bits.append(str(field_of_study).strip())
        if institution:
            education_bits.append(f"at {institution}")

        if education_bits:
            parts.append(f"Education: {' '.join(education_bits)}")
    elif isinstance(education, Sequence) and not isinstance(education, (str, bytes, bytearray)):
        education_texts = [
            _clean_text(item.get("degree", "")) if isinstance(item, Mapping) else _clean_text(item)
            for item in education
        ]
        education_texts = [item for item in education_texts if item]
        if education_texts:
            parts.append(f"Education: {', '.join(education_texts)}")

    if not parts:
        return ""

    paragraph = re.sub(r"\s+", " ", " ".join(parts)).strip()
    return paragraph


# ---------------------------------------------------------------------------
# Profile construction
# ---------------------------------------------------------------------------
def build_profile(raw_candidate: Any) -> CandidateProfile:
    """Build a normalized CandidateProfile from a raw candidate record."""
    if not isinstance(raw_candidate, Mapping):
        raise TypeError("raw_candidate must be a mapping")

    profile_payload = safe_get(raw_candidate, "profile", default={})
    if not isinstance(profile_payload, Mapping):
        profile_payload = {}

    context = dict(profile_payload)
    context.update(raw_candidate)

    candidate_id = safe_get(context, "candidate_id", "id", "uuid", default="")
    headline = safe_get(context, "headline", "profile_headline", default="")
    summary = safe_get(context, "summary", "professional_summary", "profile_summary", "about", default="")
    current_title = safe_get(context, "current_title", "title", "current_role", default="")

    career_history_input = safe_get(
        context,
        "career_history",
        "work_history",
        "employment_history",
        "experience",
        default=[],
    )
    education_input = safe_get(context, "education", "academics", default={})
    skills_input = safe_get(context, "skills", "technical_skills", default=[])
    signals_input = safe_get(context, "redrob_signals", default={})

    career_history = normalize_career_history(career_history_input)
    skills = normalize_skills(skills_input)
    education = education_input if isinstance(education_input, Mapping) else {}
    redrob_signals = signals_input if isinstance(signals_input, Mapping) else {}

    fallback_years = safe_get(context, "years_of_experience", "experience_years", default=None)
    total_experience_years = calculate_total_experience(career_history, fallback_years)

    profile_text = build_profile_text(
        headline=str(headline).strip(),
        summary=str(summary).strip(),
        current_title=str(current_title).strip(),
        skills=skills,
        career_history=career_history,
        education=education,
    )

    return CandidateProfile(
        candidate_id=str(candidate_id).strip(),
        headline=str(headline).strip(),
        summary=str(summary).strip(),
        current_title=str(current_title).strip(),
        skills=skills,
        career_history=career_history,
        total_experience_years=total_experience_years,
        education=dict(education),
        redrob_signals={
            "response_rate": _normalize_signal_value(
                redrob_signals,
                "response_rate",
                "recruiter_response_rate",
            ),
            "interview_rate": _normalize_signal_value(
                redrob_signals,
                "interview_rate",
                "interview_completion_rate",
            ),
            "offer_rate": _normalize_signal_value(
                redrob_signals,
                "offer_rate",
                "offer_acceptance_rate",
            ),
        },
        profile_text=profile_text,
    )


def load_candidates(raw_candidates: Any) -> list[CandidateProfile]:
    """Load candidate records and continue processing even when one record fails."""
    if isinstance(raw_candidates, (str, Path)):
        records = _load_records_from_path(raw_candidates)
    elif isinstance(raw_candidates, Sequence) and not isinstance(
        raw_candidates, (str, bytes, bytearray)
    ):
        records = list(raw_candidates)
    else:
        raise TypeError("raw_candidates must be a sequence of mappings or a file path")

    profiles: list[CandidateProfile] = []
    for index, raw_candidate in enumerate(records):
        try:
            if not isinstance(raw_candidate, Mapping):
                raise TypeError("Each candidate must be a mapping")
            profile = build_profile(raw_candidate)
            if profile is not None:
                profiles.append(profile)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Failed to build profile for candidate %s: %s", index, exc)

    return profiles


def _load_records_from_path(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()

    try:
        if suffix == ".json":
            with file_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, list):
                return data
            if isinstance(data, Mapping):
                return [dict(data)]
            return []

        if suffix == ".jsonl":
            rows: list[dict[str, Any]] = []
            with file_path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    stripped_line = line.strip()
                    if not stripped_line:
                        continue
                    try:
                        rows.append(json.loads(stripped_line))
                    except json.JSONDecodeError as exc:
                        logger.warning("Skipping invalid JSON on line %s of %s: %s", line_number, file_path, exc)
            return rows

        raise ValueError("Unsupported file format")
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read candidate data from {file_path}: {exc}") from exc


def _normalize_signal_value(signals: Mapping[str, Any], *keys: str, default: float = 0.5) -> float:
    """Normalize signal values to a float, falling back to the default if needed."""
    raw_value = safe_get(signals, *keys, default=default)
    numeric_value = _coerce_float(raw_value)
    return numeric_value if numeric_value is not None else default


def _coerce_float(value: Any) -> float | None:
    """Convert supported numeric values into floats, returning None otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _clean_text(value: Any) -> str:
    """Collapse repeated whitespace and trim surrounding spaces from text."""
    if value is None:
        return ""
    text = str(value).strip()
    return re.sub(r"\s+", " ", text)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    sample_candidate = {
        "candidate_id": "CAND_SAMPLE",
        "profile_headline": "Data Scientist",
        "about": "Experienced in building machine learning pipelines and analytics products.",
        "current_title": "Senior Data Scientist",
        "skills": ["Python", {"name": "PyTorch"}, "SQL"],
        "experience": [
            {"title": "Data Scientist", "years": "3"},
            {"title": "ML Engineer", "years": "2.5"},
        ],
        "academics": {"degree": "M.Tech", "institution": "IIT"},
    }

    profile = build_profile(sample_candidate)
    print(f"Candidate ID: {profile.candidate_id}")
    print(f"Total Experience: {profile.total_experience_years}")
    print(f"Profile Text: {profile.profile_text}")