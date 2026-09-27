import os
import uvicorn

if __name__ == "__main__":
    port_str = os.environ.get("PORT", "8000")
    try:
        port = int(port_str)
    except (ValueError, TypeError):
        port = 8000

    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting GramCRM server on {host}:{port} ...")
    uvicorn.run("app.main:app", host=host, port=port)
