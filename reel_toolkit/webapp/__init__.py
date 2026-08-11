"""Local drag-and-drop web UI for reel_toolkit.

Run with:
    uvicorn reel_toolkit.webapp.main:app --reload --port 8000
then open http://127.0.0.1:8000 in a browser.

This is a *local* tool -- it runs on whoever's machine starts it and writes
output into reel_toolkit/webapp/jobs/. It is not meant to be exposed on the
open internet as-is (no auth, no upload size limits).
"""
