## TDD Workflow

Use the agent in a tight red-green-refactor loop:

1. Reproduce one bug or user behavior with a failing test.
2. Make the smallest code change that turns the test green.
3. Run the narrowest relevant test subset first, then the full suite.
4. Refactor only while tests stay green.

Test layout in this repo:

- `tests/unit`: pure logic like scoring and subtitle parsing
- `tests/api`: FastAPI routes and page contract tests with an isolated SQLite database
- `tests/fixtures`: real-world subtitle snippets captured from regressions

Recommended command flow:

```bash
uv run --extra dev python -m pytest tests/unit/test_subtitle_parser.py
uv run --extra dev python -m pytest tests/api/test_sentences_api.py
uv run --extra dev python -m pytest
```
