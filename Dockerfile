FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

RUN useradd --create-home appuser
WORKDIR /home/appuser

RUN apt-get update && apt-get install -y --no-install-recommends gcc build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy application
COPY . /home/appuser/realtime_service
# Keep the container working directory at the parent so the package
# `realtime_service` can be imported as a top-level package by Python
# (uvicorn will import "realtime_service.main:app").
WORKDIR /home/appuser

# Install dependencies
RUN python -m pip install --upgrade pip
# requirements.txt lives under /home/appuser/realtime_service in this image
RUN pip install -r realtime_service/requirements.txt

EXPOSE 8001

USER appuser

CMD ["uvicorn", "realtime_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
