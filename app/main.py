from fastapi import FastAPI

app = FastAPI(title="opt-rag")


@app.get("/health")
def health():
    return {"status": "ok"}
