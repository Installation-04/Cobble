"""{{project_name}}: backend entry point."""

from fastapi import FastAPI

app = FastAPI(title="{{project_name}}")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
