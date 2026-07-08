FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    libcap2-bin \
    && groupadd --system app && useradd --system --gid app --no-create-home app \
    # iputils-ping's "ping" needs CAP_NET_RAW, granted here since we drop root below.
    && setcap cap_net_raw+ep /usr/bin/ping \
    && apt-get purge -y --auto-remove libcap2-bin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN chown -R app:app /app

USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
