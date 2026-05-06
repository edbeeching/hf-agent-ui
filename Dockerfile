FROM node:22-slim AS web

WORKDIR /app/hf_agent_ui/web
COPY hf_agent_ui/web/package*.json ./
RUN npm ci
COPY hf_agent_ui/web ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app
ENV PORT=7860

COPY pyproject.toml README.md ./
COPY hf_agent_ui ./hf_agent_ui
COPY --from=web /app/hf_agent_ui/web/dist ./hf_agent_ui/hub/static

RUN pip install --no-cache-dir .
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

EXPOSE 7860
USER appuser
CMD ["python", "-m", "uvicorn", "hf_agent_ui.hub.app:app", "--host", "0.0.0.0", "--port", "7860"]
