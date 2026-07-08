FROM python:3.12-slim

RUN pip install --no-cache-dir requests

WORKDIR /app
COPY app.py .

EXPOSE 7860
CMD ["python", "app.py", "--serve"]
