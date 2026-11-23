FROM python:3.12-slim
WORKDIR /app
COPY agents/container-app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agents/hosted/sales.py .
COPY agents/hosted/data/ data/
COPY agents/container-app/main.py .
USER 10001
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
