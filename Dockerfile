FROM python:3.12-slim

# Evita .pyc e força stdout/stderr sem buffer (logs imediatos no container).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# psycopg2-binary já traz os binários; libpq garante o cliente em runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# O compose sobrescreve com runserver em dev; este é o default de produção.
CMD ["gunicorn", "core.wsgi:application", "--bind", "0.0.0.0:8000"]
