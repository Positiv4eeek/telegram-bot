from aiogram import Router
from app.features.downloader.handlers import router as dl_router
from app.features.profile.handlers import router as profile_router

def build_router() -> Router:
    root = Router()
    root.include_router(profile_router)
    root.include_router(dl_router)
    return root
