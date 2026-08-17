# Pine Box Desktop

Electron shell for PineBoxAgent. It can launch the local FastAPI agent or
attach to an agent that is already running.

## Run

```powershell
npm install
npm run desktop
```

On Windows, run from a local path rather than a UNC network share if Electron
is blocked with `Access is denied`.

## Python Agent

The desktop app starts:

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8096
```

Use the Settings view to set a Python command, API key, custom agent URL, or
data directory. The default development data directory is `./data`; packaged
apps use the app user-data folder and set `SPARK_AGENT_DATA_DIR` for the
Python process.

If dependencies are missing, use **Install Python Deps** in the Logs/Settings
workflow or run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Linux uses `.venv/bin/python` after the same setup.

## Build

```powershell
npm run desktop:dist:win
npm run desktop:dist:linux
```

Build outputs land in `dist-desktop/`.
