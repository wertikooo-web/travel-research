from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  (registers models on Base.metadata)
from .db import Base, engine
from .routers import trips

Base.metadata.create_all(bind=engine)

app = FastAPI(title="TripMatch API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trips.router)


@app.get("/health")
def health():
    return {"status": "ok"}
