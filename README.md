# Valhallog

Valhallog is a keyboard-friendly Textual app for browsing Linux logs. The
current milestone provides a source tree on the left, a log viewer on the
right, a level selector, a status line, and a footer. Directory sources are
scanned for safe text-like files, selecting one loads its recent lines, and
journal sources read recent output from `journalctl`.

## Run it

Create a virtual environment and install the project with its development
dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Start the app either way:

```bash
.venv/bin/valhallog
# or
.venv/bin/python -m valhallog
```

Press `q` to quit, `Tab` to move focus, `Shift+H` / `Shift+L` to focus the
sources or log viewer panels, `v` to focus the `(V)ERBOSITY` menu, `j` / `k`
to move through the source tree or scroll the log viewer,
`h` / `l` to collapse or expand/open, `f` to toggle follow mode for the
selected source, `a` to add a folder source, `r` to rename the highlighted
source, and `?` to open the help screen.
The add-source picker starts in the invoking user's home directory, shows
hidden folders, offers a name input after selection, and offers recursive
scanning. Use the level selector to filter the selected source.

If your user account cannot read a system journal or a protected log file,
launch the app with elevated privileges:

```bash
sudo .venv/bin/valhallog
```

Valhallog keeps the invoking user's configuration path when launched through
`sudo`.

## Configuration

The app looks for the user configuration at
`~/.config/valhallog/config.toml`. Copy the example to get started:

```bash
mkdir -p ~/.config/valhallog
cp examples/config.example.toml ~/.config/valhallog/config.toml
```

This milestone reads the settings, scans directory sources, loads selected
regular files, follows appended file lines with `f`, and loads the configured
journal modes (`system`, `boot`, `kernel`, and `errors`) through `journalctl`.
Pressing `a` adds one folder source and saves it immediately to the TOML
configuration after confirmation. The folder name is suggested as the source
name, and duplicate folder paths are rejected. Pressing `r` renames the
highlighted configured source and saves that change immediately.
Regular-file reads run in the background so the interface remains responsive.
Plain-file filtering uses level tokens such as `DEBUG`, `INFO`, `WARN`,
`ERROR`, and `CRITICAL`; journal filtering uses native journal priorities.
Journal follow mode uses `journalctl --follow` and is limited to the most recent
2,000 viewer lines.

## Current limitations

- Existing sources can still be edited directly in TOML; new folder sources
  can also be added from inside the app with `a`.
- Plain-file severity filtering is a token-based convenience heuristic.
- Search, saved views, and advanced journal filters are not included yet.
