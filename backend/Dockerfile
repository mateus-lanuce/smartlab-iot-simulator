FROM python:3.11-alpine
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend.py .
COPY static/ ./static/
EXPOSE 8000
CMD ["python", "backend.py"]
