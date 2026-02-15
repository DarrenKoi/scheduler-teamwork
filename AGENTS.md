# Repository Guidelines

## Project Structure & Module Organization
This module is a Flask-based job scheduler with a Nuxt frontend.
- `src/`: backend application code (`app.py`, `job_manager.py`, `config.yaml`, Jinja templates).
- `jobs/`: runnable job folders (`jobs/<task_name>/main.py`, optional `job.yaml`).
- `frontend/`: Nuxt UI (`app/` for pages/components, `public/` for static assets).
- `data/`: runtime SQLite DB (`jobs.db`).
- `logs/`: scheduler and job execution logs.

Keep backend changes in `src/`, UI changes in `frontend/app/`, and job examples inside `jobs/`.

## Build, Test, and Development Commands
Run commands from `web-development/python/flask/job-scheduler` unless noted.
- `uv sync`: install backend dependencies from `pyproject.toml`.
- `uv run src/app.py`: start Flask backend on `http://localhost:5050`.
- `cd frontend && npm install`: install frontend dependencies.
- `cd frontend && npm run dev`: run Nuxt dev server on `http://localhost:3000`.
- `cd frontend && npm run lint`: run ESLint.
- `cd frontend && npm run typecheck`: run Nuxt/TypeScript checks.
- `cd frontend && npm run build`: production build validation.

## Coding Style & Naming Conventions
- Python: 4-space indentation, `snake_case` for functions/variables, `PascalCase` for classes, type hints for new/changed code.
- Vue/TypeScript: follow Nuxt + ESLint defaults; 2-space indentation (`frontend/.editorconfig`).
- File names: prefer descriptive `snake_case` or `kebab-case`, matching nearby conventions.
- Markdown/docs: concise sections, clear headings, relative links.

## Testing Guidelines
No single test suite is enforced yet.
- Frontend: run `npm run lint` and `npm run typecheck` before PRs.
- Backend: smoke-test by running `uv run src/app.py` and validating job scan/run behavior.
- For non-trivial backend logic, add `tests/` with `pytest` and `test_*.py` naming.

## Commit & Pull Request Guidelines
Recent commits use short imperative subjects (for example: `Add ...`, `Refactor ...`, `Update ...`, `Clean up ...`).
- Keep one logical change per commit.
- PRs should include purpose, affected paths, validation commands, and screenshots for UI changes.

## Security & Configuration Tips
- Do not commit secrets, API keys, or private endpoints.
- Keep environment-specific values in local overrides or environment variables.
- Review `src/config.yaml` updates carefully (port, scan interval, retention settings).
