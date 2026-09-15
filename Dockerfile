FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY pyproject.toml README.md LICENSE alembic.ini ./
COPY app ./app
# Longer timeout + retries: slow connections to PyPI otherwise fail the build.
RUN pip install --timeout 120 --retries 5 . \
    && useradd --create-home --uid 10001 appuser

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# Apply migrations, then start the API.
CMD ["sh", "-c", "python -m app db migrate && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --proxy-headers"]
