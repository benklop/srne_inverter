"""Serial transport request-echo stripping."""

from custom_components.srne_inverter.infrastructure.transport.serial_transport import (
    _strip_request_echo,
)


def test_strip_echo_when_request_is_prefix():
    request = bytes([0x01, 0x03, 0x01, 0x00, 0x00, 0x01, 0xD5, 0xCA])
    response = request + bytes([0x01, 0x03, 0x02, 0x00, 0x64, 0xB9, 0xAF])
    assert _strip_request_echo(response, request) == response[len(request) :]


def test_no_strip_when_response_is_request_only():
    request = bytes([0x01, 0x03, 0x01, 0x00, 0x00, 0x01, 0xD5, 0xCA])
    assert _strip_request_echo(request, request) == b""


def test_no_strip_when_no_prefix_match():
    request = bytes([0x01, 0x03, 0x01, 0x00, 0x00, 0x01, 0xD5, 0xCA])
    response = bytes([0x01, 0x03, 0x02, 0x00, 0x64, 0xB9, 0xAF])
    assert _strip_request_echo(response, request) is response
