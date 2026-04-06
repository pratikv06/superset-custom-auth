FROM apache/superset:4.1.1

USER root

# curl for healthcheck, requests + psycopg2 for runtime
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir requests==2.32.3 psycopg2-binary==2.9.9

# Place config files on the Python path that Superset scans at startup
COPY superset_config.py /app/pythonpath/superset_config.py
COPY custom_security.py /app/pythonpath/custom_security.py

USER superset
