from unittest.mock import MagicMock

import pytest

from demo.snowflake_reader import ensure_reader, reader_key


def test_redeployment_reuses_key_and_invalid_key_is_not_replaced(tmp_path):
    path = reader_key(tmp_path / "auth")
    original = path.read_bytes()
    assert reader_key(path.parent).read_bytes() == original
    path.write_bytes(b"invalid existing key")
    with pytest.raises(ValueError):
        reader_key(path.parent)
    assert path.read_bytes() == b"invalid existing key"


def test_public_key_mismatch_stops_before_grants(tmp_path):
    path = reader_key(tmp_path / "auth")
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [("RSA_PUBLIC_KEY_FP", "different")]
    with pytest.raises(ValueError, match="자동 교체하지"):
        ensure_reader(conn, path)
    assert not any(call.args[0].startswith("GRANT") for call in cursor.execute.call_args_list)
    assert not any("PRIVATE KEY" in str(call) for call in cursor.execute.call_args_list)
