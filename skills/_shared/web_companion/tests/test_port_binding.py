# GENERATED FILE — DO NOT EDIT. Source: github.com/petmakris/web-companion
"""A fixed port has to stay fixed, or it is not worth having.

The whole value of a memorable port is that the URL keeps working. Drifting to
the next free one destroys that quietly, and the address you reach afterwards
may belong to someone else's service — so an occupied port must fail loudly
instead.
"""
import os
import socket

import pytest

import skills._shared.web_companion.server as server_mod


def _occupy(port_hint=0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port_hint))
    s.listen()
    return s, s.getsockname()[1]


def test_a_free_port_binds():
    sock, port = server_mod._bind_first_available_port(range(56320, 56321), "127.0.0.1")
    try:
        assert port == 56320
    finally:
        sock.close()


def test_a_single_occupied_port_refuses_to_drift():
    """The regression this guards: quietly landing on port+1."""
    holder, port = _occupy()
    try:
        with pytest.raises(OSError) as excinfo:
            server_mod._bind_first_available_port(range(port, port + 1), "127.0.0.1")
        msg = str(excinfo.value)
        assert str(port) in msg, "the error does not say which port"
        assert "not available" in msg
    finally:
        holder.close()


def test_the_error_names_what_is_in_the_way():
    """'Port 3080 is taken' sends you hunting; naming the process does not."""
    holder, port = _occupy()
    try:
        detail = server_mod._port_holder(port)
        # lsof may be absent in a minimal container — then the helper degrades
        # to "" rather than breaking startup, and that is the contract.
        if detail:
            assert "pid" in detail
    finally:
        holder.close()


def test_port_holder_never_raises_on_a_free_port():
    assert server_mod._port_holder(56399) == ""


def test_a_multi_port_range_still_walks():
    """Other skills still pass windows; only the single-port case is strict."""
    holder, port = _occupy()
    try:
        sock, got = server_mod._bind_first_available_port(range(port, port + 3), "127.0.0.1")
        try:
            assert got != port and got < port + 3
        finally:
            sock.close()
    finally:
        holder.close()


def test_the_annotate_port_is_outside_the_ephemeral_range():
    """The reason for the move: the kernel hands ephemeral ports to OUTGOING
    connections, so a service pinned inside that window can lose its port to a
    browser tab while it is down."""
    import subprocess
    try:
        lo = int(subprocess.check_output(
            ["sysctl", "-n", "net.inet.ip.portrange.first"], text=True).strip())
    except (subprocess.SubprocessError, FileNotFoundError, ValueError):
        pytest.skip("no sysctl (not macOS)")
    assert 3080 < lo, "the chosen port is back inside the ephemeral range"


def test_port_zero_lets_the_os_choose():
    """How a test starts a server while the real one holds the fixed port:
    {SKILL}_PORT=0 asks the OS for any free port, and the caller has to be
    told which one it actually got."""
    sock, port = server_mod._bind_first_available_port(range(0, 1), "127.0.0.1")
    try:
        assert port != 0, "port 0 must be resolved to the real assigned port"
        assert port == sock.getsockname()[1]
    finally:
        sock.close()


def test_a_wildcard_holder_still_counts_as_taken():
    """The bug this guards, found the first time the guarantee was tested.

    SO_REUSEADDR (which we need, so a restart is not blocked by TIME_WAIT)
    lets a bind to a SPECIFIC address succeed while another process holds the
    same port on the WILDCARD address. Both then listen and requests are split
    between them at random. bind() cannot detect it; connecting can."""
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    holder.bind(("0.0.0.0", 0))          # wildcard, exactly like an exposed server
    holder.listen()
    port = holder.getsockname()[1]
    try:
        assert server_mod._port_in_use(port) is True
        with pytest.raises(OSError):
            server_mod._bind_first_available_port(range(port, port + 1), "127.0.0.1")
    finally:
        holder.close()


def test_port_in_use_is_false_for_a_free_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()                        # released, nothing listening now
    assert server_mod._port_in_use(port) is False
