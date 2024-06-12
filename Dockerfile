FROM python:3.11-slim

LABEL maintainer="vaskel <contact@vaskel.xyz>"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PYSETUP_PATH="/opt/pysetup" \
    VENV_PATH="/opt/pysetup/.venv"

ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"

RUN apt-get update \
    && apt-get install gcc git curl -y

RUN curl -sSL https://install.python-poetry.org | python3 -

WORKDIR /app
COPY poetry.lock pyproject.toml fix-artist-twitter-tags.diff ./

RUN poetry install --no-dev

# Boy do i love setting up diffs
RUN patch -p1 < fix-artist-twitter-tags.diff

COPY . /app/

CMD [ "poetry", "run", "python", "-O", "bot.py" ]