"""Calculator tool service.

A simple calculator tool that can be deployed as a containerized service.
Exposes a /invoke endpoint that accepts operations and returns results.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
import logging

app = FastAPI(
    title="Calculator Tool",
    description="A simple calculator tool for Micro ADK",
    version="1.0.0",
)

logger = logging.getLogger(__name__)


class InvokeRequest(BaseModel):
    """Request to invoke the calculator."""
    
    args: Dict[str, Any] = Field(default_factory=dict)
    context: Optional[Dict[str, Any]] = None


class InvokeResponse(BaseModel):
    """Response from the calculator."""
    
    result: Any = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "tool": "calculator"}


@app.post("/invoke", response_model=InvokeResponse)
async def invoke(request: InvokeRequest) -> InvokeResponse:
    """Invoke the calculator tool.
    
    Args in request.args:
        operation: The operation to perform (add, subtract, multiply, divide)
        a: First operand
        b: Second operand
        
    Returns:
        The calculation result.
    """
    try:
        operation = request.args.get("operation", "").lower()
        a = float(request.args.get("a", 0))
        b = float(request.args.get("b", 0))
        
        if operation == "add":
            result = a + b
        elif operation == "subtract":
            result = a - b
        elif operation == "multiply":
            result = a * b
        elif operation == "divide":
            if b == 0:
                return InvokeResponse(error="Division by zero")
            result = a / b
        elif operation == "power":
            result = a ** b
        elif operation == "modulo":
            if b == 0:
                return InvokeResponse(error="Modulo by zero")
            result = a % b
        else:
            return InvokeResponse(
                error=f"Unknown operation: {operation}. "
                      f"Supported: add, subtract, multiply, divide, power, modulo"
            )
        
        return InvokeResponse(
            result=result,
            metadata={
                "operation": operation,
                "operands": {"a": a, "b": b},
            }
        )
    
    except ValueError as e:
        return InvokeResponse(error=f"Invalid operand: {e}")
    except Exception as e:
        logger.exception("Calculator error")
        return InvokeResponse(error=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
