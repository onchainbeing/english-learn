from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.routes import router as api_router
from app.core.config import get_settings
from app.db.session import engine, get_session, init_db
from app.models import Episode

settings = get_settings()
app = FastAPI(title=settings.app_name)
app.include_router(api_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/media", StaticFiles(directory=str(settings.media_dir)), name="media")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_session)):
    episodes = db.exec(select(Episode).order_by(Episode.created_at.desc())).all()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"episodes": episodes},
    )


@app.get("/practice/{episode_id}", response_class=HTMLResponse)
def practice_page(episode_id: int, request: Request, db: Session = Depends(get_session)):
    episode = db.get(Episode, episode_id)
    if not episode:
        return HTMLResponse("Episode not found", status_code=404)

    audio_url = f"/media/{Path(episode.audio_path).name}"
    return templates.TemplateResponse(
        request=request,
        name="practice.html",
        context={"episode": episode, "audio_url": audio_url},
    )


@app.get("/healthz")
def healthz():
    return {"ok": True}
