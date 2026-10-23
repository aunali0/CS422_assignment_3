import socket
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from client import ClientConfig, data_connection
from comparison import preflight

CFG = ClientConfig(10, 5, .2, 5, 3, 3)


class SocketSelectionTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(socket, "TCP_CONGESTION", 13, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_algorithm_is_set_and_checked_before_connect(self):
        sock = MagicMock()
        with patch("client.socket.getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 5201))
        ]), patch("client.socket.socket", return_value=sock), patch(
            "client.get_tcp_algorithm", return_value="a3_cc"
        ):
            with data_connection("localhost", 5201, replace(CFG, algorithm="a3_cc")):
                pass
        names = [call[0] for call in sock.mock_calls]
        self.assertLess(names.index("setsockopt"), names.index("connect"))
        sock.setsockopt.assert_called_once_with(socket.IPPROTO_TCP, socket.TCP_CONGESTION, b"a3_cc")
        sock.__exit__.assert_called_once()

    def test_mismatch_never_connects(self):
        sock = MagicMock()
        with patch("client.socket.getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 5201))
        ]), patch("client.socket.socket", return_value=sock), patch(
            "client.get_tcp_algorithm", return_value="cubic"
        ):
            with self.assertRaises(OSError):
                with data_connection("localhost", 5201, replace(CFG, algorithm="bbr")):
                    pass
        sock.connect.assert_not_called()
        sock.close.assert_called_once()

    def test_unavailable_algorithm_fails_preflight(self):
        sock = MagicMock()
        sock.__enter__.return_value = sock
        sock.setsockopt.side_effect = OSError("unavailable")
        with patch("comparison.platform.system", return_value="Linux"), patch(
            "comparison.socket.socket", return_value=sock
        ):
            with self.assertRaisesRegex(SystemExit, "No algorithm was substituted"):
                preflight(["bbr"])


if __name__ == "__main__":
    unittest.main()
