_pending_uploads = {}

def start_upload(umo: str):
    _pending_uploads[umo] = True

def cancel_upload(umo: str):
    _pending_uploads.pop(umo, None)

def is_uploading(umo: str) -> bool:
    return umo in _pending_uploads