# Manual test checklist

Run these commands from the project root on CachyOS/Omarchy inside Hyprland.

## 1. Install and activate Python environment

```bash
python --version
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

## 2. Check local AI (optional for the first collector test)

The project uses an Ollama-compatible local server. Start Ollama and install a
small model such as the configured `qwen3:4b` model according to your local
Ollama installation. Then verify the server and model before the report test.

The report does not crash when AI is unavailable; it prints
`rules/fallback; Ollama unavailable` and retains unknown blocks for review.

## 3. Start observation

Keep this terminal open:

```bash
source .venv/bin/activate
python activity/activity_tracker.py
```

The tracker prints each committed observation. It records the focused
Hyprland client, workspace, browser context (when the browser extension is
connected), and VS Code/Git metadata. Leave it running while you test:

1. Open a VS Code project and switch between two files.
2. Switch to a Chrome/Chromium tab with the Personal OS extension enabled.
3. Visit a YouTube video, then an unrelated site.
4. Switch to another Hyprland workspace and back.

Stop the tracker with `Ctrl+C` after several minutes.

## 4. Generate the clean report

```bash
python activity/daily_report.py --date $(date +%F)
```

Expected behavior:

- The header says `local AI (Ollama)` if the model is reachable.
- Repeated filenames are not printed as the main result.
- The first time VS Code exposes a new workspace, it appears once using that
  workspace name with `needs confirmation`; it is not split into one question
  per file.
- A local preview whose URL/title explicitly names that workspace appears as a
  resource for the same proposed project.
- Unrelated searches and videos appear under `Other activity` and do not add
  time to the project.
- Unknown activity produces a `Needs your classification` section.

For a no-AI baseline:

```bash
python activity/daily_report.py --date $(date +%F) --no-llm
```

## 5. Teach unknown content

```bash
python activity/review_unclassified.py
```

For a new VS Code workspace, choose `N` and press Enter to accept the shown
workspace name as the project name, or type a better project name. This saves
an exact workspace-to-project link, so all future files in that workspace are
recognized automatically.

For an unknown site such as `tutedude.com`, choose `T`, enter `AI/ML`,
choose `Learning`, and approve learning that domain. Future matching activity
will use the saved rule in `config/topics.json`.

## 6. Inspect the stored facts

```bash
python activity/session_report.py --limit 20
```

This command is a legacy diagnostic view. Use `daily_report.py` for the
human-facing output described above.
