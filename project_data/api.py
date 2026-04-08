from pathlib import Path
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def load_json_file(filename: str):
    file_path = DATA_DIR / filename

    if not file_path.exists():
        return {"error": f"{filename} not found"}

    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/")
def root():
    return {"message": "Project Sparkes API is running"}


@app.get("/weights")
def get_weights():
    return load_json_file("weights.json")


@app.get("/steps")
def get_steps():
    return load_json_file("daily_steps.json")