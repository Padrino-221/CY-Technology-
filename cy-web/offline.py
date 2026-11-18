"""Retire previously installed offline service workers."""
from django.conf import settings
from django.http import FileResponse
from django.views.decorators.http import require_GET


@require_GET
def worker(request):
    response = FileResponse(
        (settings.BASE_DIR / "static" / "offline-worker.js").open("rb"),
        content_type="text/javascript",
    )
    response["Cache-Control"] = "no-store"
    return response
