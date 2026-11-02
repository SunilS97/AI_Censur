from fastapi import APIRouter

from ai_censur.api.routers import audio, auth, sound_effects, users

# Registered by `main.py`, in the order the endpoints appear in the API docs.
all_routers: tuple[APIRouter, ...] = (
    audio.router,
    sound_effects.router,
    users.router,
    auth.router,
)

__all__ = ["all_routers"]
