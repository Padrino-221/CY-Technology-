import re
from uuid import UUID

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET

from credit.models import OfflineReceipt, OfflineRevision

OPERATIONS = re.compile(
    r"/(?:(?:customers|inventory|sales|payments)/(?:new|[0-9]+/(?:edit|delete)|"
    r"[0-9]+)/|inventory/[0-9]+/release/|sales/[0-9]+/(?:return|refund)/|settings/)"
)


def is_operation(path):
    if re.fullmatch(r"/(?:customers|inventory|sales)/[0-9]+/", path):
        return False
    return OPERATIONS.fullmatch(path) is not None


@require_GET
def worker(request):
    response = FileResponse((settings.BASE_DIR / "static" / "offline-worker.js").open("rb"), content_type="text/javascript")
    response["Cache-Control"] = "no-cache"
    return response


@require_GET
def session(request):
    if not request.user.is_authenticated:
        return JsonResponse({}, status=401)
    response = JsonResponse({"user": str(request.user.pk), "csrf": get_token(request)})
    response["Cache-Control"] = "no-store"
    return response


class OfflineMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        operation = request.headers.get("X-CY-Operation")
        if operation and (
            request.method != "POST" or not is_operation(request.path)
            or not request.user.is_authenticated
            or request.headers.get("X-CY-User") != str(request.user.pk)
        ):
            return JsonResponse({"error": "Sign in with the account that saved this change."}, status=403)
        if not request.user.is_authenticated:
            return self.get_response(request)
        if request.method == "GET":
            revision = OfflineRevision.objects.filter(pk=1).values_list("version", flat=True).first() or 0
            request.offline_revision = revision
            response = self.get_response(request)
            if (request.path not in {"/account/password/", "/login/", "/logout/"}
                    and response.status_code == 200
                    and response.get("Content-Type", "").startswith("text/html")):
                response["X-CY-Offline-Page"] = str(request.user.pk)
            return response
        if request.method != "POST" or not is_operation(request.path):
            response = self.get_response(request)
            if request.path == "/logout/" and request.method == "POST" and response.status_code == 302:
                response["Clear-Site-Data"] = '"cache"'
            return response
        # SQLite uses IMMEDIATE transactions in both supported settings modules.
        with transaction.atomic():
            revision, _ = OfflineRevision.objects.select_for_update().get_or_create(pk=1)
            if operation:
                try:
                    key = UUID(operation)
                    baseline = int(request.headers.get("X-CY-Revision", ""))
                except ValueError:
                    return JsonResponse({"error": "Invalid queued operation."}, status=400)
                receipt = OfflineReceipt.objects.filter(pk=key, user_id=request.user.pk).first()
                if receipt:
                    return JsonResponse({"revision": receipt.version})
                if baseline != revision.version:
                    return JsonResponse({"error": "Server records changed. Review this submission before retrying."}, status=409)
            response = self.get_response(request)
            rejected = any(message.level >= messages.ERROR for message in getattr(request._messages, "_queued_messages", ()))
            if response.status_code == 302 and not rejected:
                revision.version += 1
                revision.save(update_fields=["version"])
                if operation:
                    OfflineReceipt.objects.create(id=key, user_id=request.user.pk, version=revision.version)
                    return JsonResponse({"revision": revision.version, "location": response["Location"]})
            if operation and response.status_code < 500:
                return JsonResponse({"error": "The server could not accept these values. Open the form to review them."}, status=422)
            return response
