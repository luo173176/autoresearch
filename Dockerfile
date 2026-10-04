FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md requirements.lock ./
COPY src ./src
COPY migrations ./migrations

RUN pip install --no-cache-dir -r requirements.lock \
    && pip install --no-cache-dir --no-deps .

EXPOSE 8000 8501

CMD ["uvicorn", "autoresearch.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
