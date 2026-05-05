FROM node:22-slim AS web

WORKDIR /app/switch/web
COPY switch/web/package*.json ./
RUN npm ci
COPY switch/web ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app
ENV PORT=7860

COPY pyproject.toml README.md ./
COPY switch ./switch
COPY --from=web /app/switch/web/dist ./switch/hub/static

RUN pip install --no-cache-dir .
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

EXPOSE 7860
USER appuser
CMD ["python", "-m", "uvicorn", "switch.hub.app:app", "--host", "0.0.0.0", "--port", "7860"]
