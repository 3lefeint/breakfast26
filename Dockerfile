FROM node:22-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

# ffmpeg is needed at runtime by tools/generate_voicepack.py's silence-trim
# step (regenerating the voice pack from the Settings tab).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY breakfast/ ./breakfast/
COPY tools/ ./tools/
COPY --from=frontend-builder /frontend/dist ./breakfast/web/dist

# All of the app's config/data defaults (config.toml, stats.db, sessions/,
# sounds/) are plain relative paths resolved against the process cwd — so
# running from here instead of /app means every one of them lands under a
# single mounted directory with zero Python code changes. main.py is still
# invoked by absolute path, so `from breakfast import ...` keeps resolving
# normally (Python adds the *script's* directory to sys.path, not the cwd).
WORKDIR /app/data

EXPOSE 8080

ENTRYPOINT ["python", "/app/main.py"]
