FROM python:3.10-slim-bookworm

WORKDIR /app/backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends libgl1 libglib2.0-0 ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./
RUN useradd --uid 10001 --create-home ssdd && mkdir -p /app/runs /app/models /app/datasets && chown -R ssdd:ssdd /app
USER ssdd

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000 --no-access-log"]
