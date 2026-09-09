FROM python:3.12-slim
WORKDIR /app
COPY API/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY API /app/API
CMD ["uvicorn", "API.app:app", "--host", "0.0.0.0", "--port", "10000"]
