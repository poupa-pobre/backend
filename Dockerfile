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

# Garante o bit de execução do entrypoint de produção e os diretórios servidos.
RUN chmod +x /app/entrypoint.sh && mkdir -p /app/staticfiles /app/media

EXPOSE 8000

# O compose de dev sobrescreve com runserver; o de prod chama o entrypoint.sh.
CMD ["gunicorn", "core.wsgi:application", "--bind", "0.0.0.0:8000"]
