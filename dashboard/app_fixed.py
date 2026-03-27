# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import logging
import random
import pandas as pd
import matplotlib.pyplot as plt
import io
import base64

# Set up logging
logging.basicConfig(level=logging.INFO)

app = FastAPI()

# CORS middleware — restrict to known origins; never use ["*"] with credentials
import os as _os  # noqa: E402

_raw_origins = _os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000"
)
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/healthcheck")
def read_healthcheck():
    logging.info("Health check endpoint called")
    return {"status": "healthy"}


@app.get("/data")
def read_data():
    try:
        # Simulate data retrieval (replace with real data retrieval logic)
        data = pd.DataFrame(
            {"x": range(10), "y": [random.randint(0, 10) for _ in range(10)]}
        )
        logging.info("Data retrieved successfully")
        return data.to_dict(orient="records")
    except Exception as e:
        logging.error(f"Error retrieving data: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@app.get("/chart", response_class=HTMLResponse)
def get_chart():
    try:
        data = pd.DataFrame(
            {"x": range(10), "y": [random.randint(0, 10) for _ in range(10)]}
        )
        plt.figure()
        plt.plot(data["x"], data["y"], marker="o")
        plt.title("Random Chart")
        plt.xlabel("X-axis")
        plt.ylabel("Y-axis")
        plt.grid()
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        logging.info("Chart generated successfully")
        return f"<img src='data:image/png;base64,{img_base64}'/>"
    except Exception as e:
        logging.error(f"Error generating chart: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
