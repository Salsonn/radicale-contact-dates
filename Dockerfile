# Use a lightweight Python base image
FROM python:3-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Copy the Python script and config file
COPY contact_dates.py /app/

# Run the Python script when the container starts
CMD ["python3", "/app/contact_dates.py", "--config", "/config/config.json", "--root", "/data/collections/collection-root"]
