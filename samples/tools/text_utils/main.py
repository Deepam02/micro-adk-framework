from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any

app = FastAPI(title="Text Utils Tool")


class InvokeRequest(BaseModel):
    args: dict[str, Any]


class InvokeResponse(BaseModel):
    result: Any


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/invoke")
def invoke(request: InvokeRequest) -> InvokeResponse:
    """
    Text utility operations.
    
    Supported operations:
    - word_count: Count words in text
    - char_count: Count characters in text
    - reverse: Reverse the text
    - uppercase: Convert to uppercase
    - lowercase: Convert to lowercase
    - title_case: Convert to title case
    """
    args = request.args
    operation = args.get("operation", "").lower()
    text = args.get("text", "")
    
    if not text:
        return InvokeResponse(result={"error": "Missing 'text' parameter"})
    
    if operation == "word_count":
        count = len(text.split())
        return InvokeResponse(result={"word_count": count, "text": text})
    
    elif operation == "char_count":
        count = len(text)
        count_no_spaces = len(text.replace(" ", ""))
        return InvokeResponse(result={
            "char_count": count,
            "char_count_no_spaces": count_no_spaces,
            "text": text
        })
    
    elif operation == "reverse":
        reversed_text = text[::-1]
        return InvokeResponse(result={"reversed": reversed_text, "original": text})
    
    elif operation == "uppercase":
        return InvokeResponse(result={"uppercase": text.upper(), "original": text})
    
    elif operation == "lowercase":
        return InvokeResponse(result={"lowercase": text.lower(), "original": text})
    
    elif operation == "title_case":
        return InvokeResponse(result={"title_case": text.title(), "original": text})
    
    else:
        return InvokeResponse(result={
            "error": f"Unknown operation: {operation}",
            "supported": ["word_count", "char_count", "reverse", "uppercase", "lowercase", "title_case"]
        })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
