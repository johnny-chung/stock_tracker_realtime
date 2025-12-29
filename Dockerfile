FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

RUN useradd --create-home appuser
WORKDIR /home/appuser

RUN apt-get update && apt-get install -y --no-install-recommends gcc build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy application
COPY . /home/appuser/realtime_service
WORKDIR /home/appuser/realtime_service

# Install dependencies
RUN python -m pip install --upgrade pip
RUN pip install -r requirements.txt

EXPOSE 8001

USER appuser

CMD ["uvicorn", "realtime_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
