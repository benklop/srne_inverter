from custom_components.srne_inverter.domain.helpers.transformations import (
    decode_string_low_bytes,
)


def test_decode_string_low_bytes_stops_at_nul() -> None:
    # "E60ABC" + NUL, remaining words ignored
    words = [
        ord("E"),
        ord("6"),
        ord("0"),
        ord("A"),
        ord("B"),
        ord("C"),
        0x0000,
        ord("Z"),
    ]
    assert decode_string_low_bytes(words) == "E60ABC"


def test_decode_string_low_bytes_uses_low_byte_only() -> None:
    # High byte is invalid per SRNE doc; ensure we ignore it.
    # word: 0x41FF should decode to 'ÿ'? No: low byte 0xFF is non-printable,
    # should become '?'. Low byte for 'A' is 0x41.
    words = [0x5A41, 0x0042]  # 'A', 'B' in low bytes
    assert decode_string_low_bytes(words) == "AB"

