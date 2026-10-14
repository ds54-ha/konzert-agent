FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Zurich
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY konzert_agent ./konzert_agent
COPY config.yaml .

RUN useradd -u 1000 -m agent && mkdir -p /app/data && chown -R agent /app/data
USER agent

EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health')"
CMD ["python", "-m", "konzert_agent", "serve"]
