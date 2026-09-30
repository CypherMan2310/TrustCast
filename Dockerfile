# TRUSTCAST API (FastAPI). Data is mounted, never baked into the image.
#   docker build -t trustcast-api .
#   docker run -p 8000:8000 -v "$PWD/data:/app/data" -v "$PWD/reports:/app/reports" trustcast-api
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TRUSTCAST_DATA_DIR=/app/data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir --no-deps -e .
EXPOSE 8000
CMD ["uvicorn", "trustcast.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
