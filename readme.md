# AI Recruiter

A lightweight Python utility for building normalized candidate profiles from raw recruiting data.

## Project structure
- src/embeddings/profile_builder.py: profile normalization and candidate loading logic
- tests/test_profile_builder.py: regression tests for the builder
- data/: sample candidate data

## Quick checks
- python -m pytest -v
- python -m py_compile src/embeddings/profile_builder.py tests/test_profile_builder.py
- python src/embeddings/profile_builder.py
