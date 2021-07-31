FROM python:3.8.10-slim-buster

#RUN apt-get -y install python3 python3-pip

ARG YOUR_ENV

ENV YOUR_ENV=${YOUR_ENV} \
  PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PIP_NO_CACHE_DIR=off \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100 \
  POETRY_VERSION=1.0.0

# System deps:
RUN pip3 install "poetry==$POETRY_VERSION"

# Copy only requirements to cache them in docker layer
WORKDIR /app/
COPY poetry.lock pyproject.toml /app/

# Project initialization:
RUN poetry config virtualenvs.create false \
  && poetry install $(test "$YOUR_ENV" == production && echo "--no-dev") --no-interaction --no-ansi

# Set up flask environment
env FLASK_APP=rstblog

# Creating folders, and files for a project:
COPY . /app/

ENTRYPOINT ["/bin/sh", "-c", "poetry run flask run --host=0.0.0.0"]
