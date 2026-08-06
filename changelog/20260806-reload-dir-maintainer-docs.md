# Document `--reload-dir` / `UVICORN_RELOAD_DIRS` in the maintainer docs

## Task Specification

The user reported that `uv run uvicorn app.main:app --reload` picks up file changes in
unrelated git worktrees under `.claude/`, triggering spurious reloads. They asked how to
scope the watcher, expressed a preference for `--reload-dir` over `--reload-exclude`, then
asked whether the setting could live in a config file rather than being passed each time.

Final scope: document the option in the maintainer docs, at the place where `--reload` is
already documented — `docs/maintainers/development.md` §"Running the app".

## Findings (verified against the installed uvicorn, 0.51+)

- Uvicorn has **no config file of its own**: no `uvicorn.toml`, no `[tool.uvicorn]` section
  in `pyproject.toml`. Configuration is CLI flags, `UVICORN_*` env vars, or `uvicorn.run()`
  keyword arguments.
- `UVICORN_RELOAD_DIRS=app` **works**. Confirmed by running the server: it logs
  `Will watch for changes in these directories: ['/home/kena/src/battery-sim/app']`.
  The env var name derives from click's `auto_envvar_prefix="UVICORN"` on the command plus
  the option's parameter name `reload_dirs` (plural — the flag is singular `--reload-dir`,
  the parameter is plural, and the env var follows the parameter).
- The env var accepts **only one directory**. `--reload-dir` is `multiple=True` with
  `type=click.Path(exists=True)`, but click does not split the env var value; the whole
  string is passed to `Path(exists=True)`. Both `"app scripts"` and `"app,scripts"` fail
  with `Error: Invalid value for '--reload-dir': Path 'app scripts' does not exist.`
  Multiple directories require repeated `--reload-dir` flags.
- `--env-file` is **not** an escape hatch: the uvicorn docs state that `UVICORN_*` variables
  cannot be read from an environment configuration file, as they are consumed before it is
  loaded.
- One directory is sufficient here: `app/` contains the Python sources, Jinja templates,
  static files and locales, so nothing that should trigger a reload lives outside it.

## High-Level Decisions

- **Document, do not automate.** The user asked for documentation at the existing `--reload`
  site. No Makefile, npm `dev` script, or `uvicorn.run()` change is made. The repo has no
  Makefile or justfile today, and adding a task runner is a larger change than was asked for.
- **Present the flag as the primary form, the env var as the persistent alternative.**
  The flag is self-contained and composes; the env var is what answers the "so I don't have
  to type it every time" question.
- **State the single-directory limitation inline.** It is a real trap: the plural env var
  name invites a list, and the failure mode is a confusing `Path does not exist` error rather
  than anything that names the true cause.
- **Do not name `.claude/` as the motivating case.** Agent worktrees are a local artifact of
  this user's setup, not a property of the repository. The doc gives the general reason
  (uvicorn watches the whole CWD) so it stays true regardless of what sits beside `app/`.

## Rationales and Alternatives

- `--reload-exclude '.claude/*'` was the first suggestion and was set aside. It is a
  blacklist, so each new stray directory needs another pattern; `--reload-dir` is a
  whitelist and is robust to whatever else appears in the working tree.
- A `dev` script in `package.json` was floated. Rejected for now: `package.json` is
  documented as dev-time-only for the Tailwind toolchain, and routing Python server startup
  through npm would blur that boundary.

## Files Modified

- `docs/maintainers/development.md` — added §"Scoping the reload watcher" under
  §"Running the app", covering the `--reload-dir` flag, the `UVICORN_RELOAD_DIRS` env var,
  the single-directory caveat, and the `--env-file` exclusion. The unscoped `--reload`
  quickstart line was left in place so the getting-started command stays minimal.
  Also added an `## Assets` heading for the pre-existing stylesheet/Plotly paragraph, which
  would otherwise have read as part of the new subsection, and updated the top-of-file
  comment to match the new section list.
- `changelog/20260806-reload-dir-maintainer-docs.md` — this file.

## Verification

Both documented commands were run against the repo and log
`Will watch for changes in these directories: ['/home/kena/src/battery-sim/app']`:

- `uv run uvicorn app.main:app --reload --reload-dir app`
- `UVICORN_RELOAD=true UVICORN_RELOAD_DIRS=app uv run uvicorn app.main:app`

## Obstacles and Solutions

- Initial guess that the env var splits on whitespace or commas was wrong — corrected by
  reading the click option definition in `uvicorn/main.py` and running both forms.
- `uv run python -c "import uvicorn.main; print(uvicorn.main.__file__)"` fails because the
  click `Command` object shadows the module name; resolved by deriving the path from
  `uvicorn.__file__` instead.

## Current Status

Findings verified. Awaiting approval of the documentation edit before changing
`docs/maintainers/development.md`.
