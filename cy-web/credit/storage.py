from django.core.files.storage import Storage


class DisabledPhotoStorage(Storage):
    def _open(self, name, mode="rb"):
        raise FileNotFoundError(name)

    def _save(self, name, content):
        raise OSError("Photo storage is not configured.")

    def delete(self, name):
        return None
