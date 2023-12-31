FROM python:3.11.7-alpine

RUN apk update && \
    apk add git && \
    apk cache clean && rm -rf /tmp/* /var/tmp/*

ARG YOUR_ENV

ENV YOUR_ENV=${YOUR_ENV} \
  PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PIP_NO_CACHE_DIR=off \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100 \
  POETRY_VERSION=1.4.2

# System deps:
RUN pip3 install "poetry==$POETRY_VERSION" gevent

# Copy only requirements to cache them in docker layer
WORKDIR /app/
COPY poetry.lock pyproject.toml /app/

# Project initialization:
RUN poetry config virtualenvs.create false \
  && poetry install -vvv --no-dev --no-interaction --no-ansi

# Set up flask environment
env FLASK_APP=app

# Creating folders, and files for a project:
COPY . /app/
