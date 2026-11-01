"""Entry point: uvicorn --factory progress_endpoint.main:app"""

from fastapi import FastAPI

from progress_endpoint.app import create_app
from progress_endpoint.config import Config
from progress_endpoint.logs import configure_logging


def app() -> FastAPI:
    configure_logging()
    return create_app(Config.from_env())
