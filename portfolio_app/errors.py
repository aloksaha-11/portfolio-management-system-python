class ApiError(Exception):
    """An error returned to the browser as {"error": code, "message": message}."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def invalid_request():
    return ApiError(400, "invalid_request", "Request body is missing or malformed.")
