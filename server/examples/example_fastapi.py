import sys
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from volview_server import VolViewApi

# Import the VolView example API
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from example_api import volview


app = FastAPI()

# Adds volview middlware
app.add_middleware(volview)

# Set CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://volview-frontend-int-449134413394.asia-east1.run.app",
        "https://idental-blazor-int-449134413394.asia-east1.run.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def index():
    return {"hello": "world"}
