import socket

from whaat.platform.system import system


class InstanceRunningError(Exception):
    def __init__(self, host: str, port: int) -> None:
        super().__init__(f"another server already listens on {host}:{port}")
        self.host = host
        self.port = port


def bind_listener(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # SO_REUSEADDR on Windows lets a second server bind a port that is in use; there only exclusive use refuses it
    option = getattr(socket, "SO_EXCLUSIVEADDRUSE") if system() == "windows" else socket.SO_REUSEADDR  # noqa: B009
    sock.setsockopt(socket.SOL_SOCKET, option, 1)
    try:
        sock.bind((host, port))
        sock.listen()
    except OSError as err:
        sock.close()
        raise InstanceRunningError(host, port) from err
    return sock
