"""SSH tunnel manager using paramiko for local port forwarding.

Creates a local listening socket that forwards connections through SSH
to the target database host:port (standard local port forwarding).
"""

from __future__ import annotations

import socket
import threading
from typing import Optional

import paramiko

from open_navicat.models.connection import ConnectionInfo


class SSHTunnel:
    """Manages an SSH port-forward tunnel to the target database host."""

    def __init__(self, info: ConnectionInfo) -> None:
        self._info = info
        self._client: paramiko.SSHClient | None = None
        self._local_port: int = 0
        self._server_sock: socket.socket | None = None
        self._running = False

    @property
    def local_port(self) -> int:
        return self._local_port

    def connect(self) -> bool:
        """Establish SSH connection and start local port forwarding."""
        try:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            kwargs: dict = {
                "hostname": self._info.ssh_host,
                "port": self._info.ssh_port or 22,
                "username": self._info.ssh_user,
                "timeout": self._info.connect_timeout or 10,
            }

            if self._info.ssh_key_file:
                key = paramiko.RSAKey.from_private_key_file(self._info.ssh_key_file)
                kwargs["pkey"] = key
            else:
                kwargs["password"] = self._info.ssh_password

            self._client.connect(**kwargs)
            self._transport = self._client.get_transport()

            # Start local port forwarding
            self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_sock.bind(("127.0.0.1", 0))
            self._server_sock.listen(5)
            self._local_port = self._server_sock.getsockname()[1]
            self._running = True

            # Forwarding thread
            def _forward() -> None:
                while self._running:
                    try:
                        client_sock, _ = self._server_sock.accept()
                        threading.Thread(
                            target=self._handle_client,
                            args=(client_sock,),
                            daemon=True,
                        ).start()
                    except Exception:
                        break

            threading.Thread(target=_forward, daemon=True).start()
            return True

        except Exception:
            self.close()
            return False

    def _handle_client(self, client_sock: socket.socket) -> None:
        """Forward a single client connection through SSH to the target."""
        try:
            remote_host = self._info.host
            remote_port = self._info.port
            channel = self._transport.open_channel(
                "direct-tcpip",
                (remote_host, remote_port),
                ("127.0.0.1", 0),
            )
            if channel is None:
                client_sock.close()
                return

            # Bidirectional forwarding
            def _forward(src, dst):
                try:
                    while True:
                        data = src.recv(4096)
                        if not data:
                            break
                        dst.send(data)
                except Exception:
                    pass
                finally:
                    try:
                        src.close()
                    except Exception:
                        pass
                    try:
                        dst.close()
                    except Exception:
                        pass

            t1 = threading.Thread(target=_forward, args=(client_sock, channel), daemon=True)
            t2 = threading.Thread(target=_forward, args=(channel, client_sock), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        except Exception:
            try:
                client_sock.close()
            except Exception:
                pass

    def close(self) -> None:
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
            self._server_sock = None
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def is_active(self) -> bool:
        return self._transport is not None and self._transport.is_active()
