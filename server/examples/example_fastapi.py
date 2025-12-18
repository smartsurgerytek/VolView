import sys
import os

from fastapi import FastAPI, Request  # ✅ Added Request import
from fastapi.middleware.cors import CORSMiddleware

from volview_server import VolViewApi

# Import the VolView example API
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from example_api import volview


app = FastAPI()


@app.middleware("http")
async def log_cors_headers(request: Request, call_next):
    response = await call_next(request)
    print(f"===============logs start=================")
    print(f"Request URL: {request.url}")
    print(f"Origin: {request.headers.get('origin')}")
    print(f"CORS headers applied: {response.headers.get('access-control-allow-origin')}")
    print(f"===============logs end===================")
    return response



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

# Adds volview middleware
app.add_middleware(volview)



@app.get("/")
def index():
    return {"hello": "world"}
