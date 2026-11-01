FROM python:3.13.18-slim-trixie AS build
ENV UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.13.6
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.13.18-slim-trixie
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && install -d -o app -g app /data
WORKDIR /app
COPY --from=build /app/.venv .venv
COPY progress_endpoint progress_endpoint
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
CMD ["uvicorn", "--factory", "progress_endpoint.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
