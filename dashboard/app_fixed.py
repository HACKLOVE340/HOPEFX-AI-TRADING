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

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update this to your allowed origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.get("/healthcheck")
def read_healthcheck():
    logging.info("Health check endpoint called")
    return {"status": "healthy"}

@app.get("/data")
def read_data():
    try:
        # Simulate data retrieval (replace with real data retrieval logic)
        data = pd.DataFrame({
            "x": range(10),
            "y": [random.randint(0, 10) for _ in range(10)]
        })
        logging.info("Data retrieved successfully")
        return data.to_dict(orient="records")
    except Exception as e:
        logging.error(f"Error retrieving data: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.get("/chart", response_class=HTMLResponse)
def get_chart():
    try:
        data = pd.DataFrame({
            "x": range(10),
            "y": [random.randint(0, 10) for _ in range(10)]
        })
        plt.figure()
        plt.plot(data['x'], data['y'], marker='o')
        plt.title('Random Chart')
        plt.xlabel('X-axis')
        plt.ylabel('Y-axis')
        plt.grid()
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        logging.info("Chart generated successfully")
        return f"<img src='data:image/png;base64,{img_base64}'/>"
    except Exception as e:
        logging.error(f"Error generating chart: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
