FROM python:3.12-slim

WORKDIR /app/user_agent
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8088
CMD ["python", "main.py"]
