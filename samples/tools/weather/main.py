"""
Weather Tool Service
Uses WeatherAPI.com to fetch real weather data.
"""
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any, Optional
import httpx
import os

app = FastAPI(title="Weather Tool")

# API key from environment variable or fallback
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "6a205a738609454dbb655753260201")
WEATHER_API_URL = "https://api.weatherapi.com/v1/current.json"


class InvokeRequest(BaseModel):
    """Standard tool invoke request."""
    args: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None


class InvokeResponse(BaseModel):
    """Standard tool invoke response."""
    ok: bool = True
    result: Optional[Any] = None
    error: Optional[str] = None


async def get_weather(location: str) -> Dict[str, Any]:
    """Fetch real weather data from WeatherAPI.com"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                WEATHER_API_URL,
                params={"key": WEATHER_API_KEY, "q": location}
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract and simplify relevant data
            return {
                "location": data["location"]["name"],
                "region": data["location"]["region"],
                "country": data["location"]["country"],
                "temperature_c": data["current"]["temp_c"],
                "temperature_f": data["current"]["temp_f"],
                "condition": data["current"]["condition"]["text"],
                "humidity": data["current"]["humidity"],
                "wind_kph": data["current"]["wind_kph"],
                "wind_mph": data["current"]["wind_mph"],
                "feels_like_c": data["current"]["feelslike_c"],
                "feels_like_f": data["current"]["feelslike_f"]
            }
    except httpx.HTTPStatusError as e:
        raise ValueError(f"Weather API error: {e.response.status_code}")
    except Exception as e:
        raise ValueError(f"Failed to fetch weather: {str(e)}")


@app.post("/invoke", response_model=InvokeResponse)
async def invoke(request: InvokeRequest):
    """Tool invocation endpoint."""
    try:
        args = request.args
        location = args.get("location")
        
        if not location:
            raise ValueError("Location is required")
        
        result = await get_weather(location)
        
        return InvokeResponse(ok=True, result=result)
    
    except Exception as e:
        return InvokeResponse(ok=False, error=str(e))


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
