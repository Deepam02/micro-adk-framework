"""Weather tool service.

A mock weather tool that simulates fetching weather data.
Demonstrates how to structure a tool that calls external APIs.
"""

from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
import logging
import random

app = FastAPI(
    title="Weather Tool",
    description="A mock weather tool for Micro ADK",
    version="1.0.0",
)

logger = logging.getLogger(__name__)


class InvokeRequest(BaseModel):
    """Request to invoke the weather tool."""
    
    args: Dict[str, Any] = Field(default_factory=dict)
    context: Optional[Dict[str, Any]] = None


class InvokeResponse(BaseModel):
    """Response from the weather tool."""
    
    result: Any = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# Mock weather data
MOCK_WEATHER = {
    "new york": {"temp": 72, "condition": "Partly Cloudy", "humidity": 65},
    "london": {"temp": 55, "condition": "Rainy", "humidity": 80},
    "tokyo": {"temp": 68, "condition": "Sunny", "humidity": 50},
    "paris": {"temp": 62, "condition": "Cloudy", "humidity": 70},
    "sydney": {"temp": 78, "condition": "Sunny", "humidity": 45},
}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "tool": "weather"}


@app.post("/invoke", response_model=InvokeResponse)
async def invoke(request: InvokeRequest) -> InvokeResponse:
    """Invoke the weather tool.
    
    Args in request.args:
        location: The city to get weather for
        unit: Temperature unit (celsius or fahrenheit, default: fahrenheit)
        
    Returns:
        Weather information for the location.
    """
    try:
        location = request.args.get("location", "").lower().strip()
        unit = request.args.get("unit", "fahrenheit").lower()
        
        if not location:
            return InvokeResponse(error="Location is required")
        
        # Get mock weather or generate random
        if location in MOCK_WEATHER:
            weather = MOCK_WEATHER[location].copy()
        else:
            # Generate random weather for unknown locations
            weather = {
                "temp": random.randint(40, 90),
                "condition": random.choice(["Sunny", "Cloudy", "Rainy", "Partly Cloudy"]),
                "humidity": random.randint(30, 90),
            }
        
        # Convert temperature if needed
        temp = weather["temp"]
        if unit == "celsius":
            temp = round((temp - 32) * 5 / 9, 1)
            temp_str = f"{temp}°C"
        else:
            temp_str = f"{temp}°F"
        
        return InvokeResponse(
            result={
                "location": location.title(),
                "temperature": temp_str,
                "condition": weather["condition"],
                "humidity": f"{weather['humidity']}%",
            },
            metadata={
                "source": "mock_weather_service",
                "unit": unit,
            }
        )
    
    except Exception as e:
        logger.exception("Weather tool error")
        return InvokeResponse(error=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
