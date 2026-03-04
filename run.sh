#!/usr/bin/env bash
set -e

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r backend/requirements.txt

if [ ! -d frontend/node_modules ]; then
  cd frontend && npm install && cd - >/dev/null
fi

uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
kill $API_PID
