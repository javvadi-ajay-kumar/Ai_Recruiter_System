import pytest

from src.embeddings.profile_builder import CandidateProfile, build_profile, load_candidates


def test_build_profile_handles_alternative_field_names_and_missing_values():
    raw_candidate = {
        "id": "CAND_123",
        "profile_headline": "ML Engineer",
        "about": "Experienced engineer.",
        "current_title": "Senior ML Engineer",
        "skills": ["Python", {"name": "PyTorch"}, "SQL"],
        "experience": [
            {"title": "ML Engineer", "years": "2"},
            {"title": "Data Engineer", "years": "3.5"},
            {"title": "Bad Entry", "years": "invalid"},
        ],
        "academics": {"degree": "B.Tech", "institution": "IIT"},
    }

    profile = build_profile(raw_candidate)

    assert isinstance(profile, CandidateProfile)
    assert profile.candidate_id == "CAND_123"
    assert profile.headline == "ML Engineer"
    assert profile.summary == "Experienced engineer."
    assert profile.current_title == "Senior ML Engineer"
    assert profile.skills == ["Python", "PyTorch", "SQL"]
    assert profile.total_experience_years == pytest.approx(5.5)
    assert profile.education == {"degree": "B.Tech", "institution": "IIT"}
    assert profile.redrob_signals["response_rate"] == 0.5
    assert profile.profile_text


def test_load_candidates_continues_after_invalid_record():
    records = [
        {"candidate_id": "OK", "profile": {"headline": "Engineer"}, "career_history": []},
        None,
    ]

    profiles = load_candidates(records)

    assert len(profiles) == 1
    assert profiles[0].candidate_id == "OK"
