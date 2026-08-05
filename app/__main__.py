"""`python -m app` — the module entry point, delegating to the desktop launcher.

Exists so that `uv run python -m app` from a source checkout runs exactly what the packaged
application will run: the frozen entry point is a script that calls `app.desktop.main()`, and
so is this. Keeping the two identical means the launcher is exercised in development rather
than only after a build.

Deliberately thin — no argument handling, no environment setup. All of that belongs in
`app.desktop`, which the frozen build reaches without passing through this file.
"""

from app.desktop import main

if __name__ == "__main__":
    main()
