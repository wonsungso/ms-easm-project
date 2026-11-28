"""Maintain a separate, persistent RSA key for the demo's Snowflake connection."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from demo.auth import restrict_directory


def reader_key(directory: Path) -> Path:
    resolved = directory.resolve()
    repository = Path(__file__).resolve().parents[1]
    if resolved.is_relative_to(repository) or resolved in (Path.home(), Path(resolved.anchor)):
        raise ValueError("RSA는 저장소·홈 루트가 아닌 전용 외부 폴더에 보관하세요.")
    if directory.is_symlink():
        raise ValueError("RSA 폴더에는 심볼릭 링크를 사용할 수 없습니다.")
    directory.mkdir(parents=True, exist_ok=True)
    restrict_directory(directory)
    path = directory / "snowflake-reader.p8"
    if path.is_symlink():
        raise ValueError("RSA 파일에는 심볼릭 링크를 사용할 수 없습니다.")
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("기존 Snowflake RSA 키 형식·크기를 확인하세요. 자동 교체하지 않습니다.")
        return path
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    payload = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
    return path


def ensure_reader(connection: Any, path: Path) -> None:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(public).digest()).decode("ascii")
    encoded = base64.b64encode(public).decode("ascii")
    with connection.cursor() as cursor:
        cursor.execute("CREATE ROLE IF NOT EXISTS EASM_AGENT365_READER")
        cursor.execute(
            "CREATE USER IF NOT EXISTS EASM_AGENT365_SERVICE TYPE = SERVICE "
            "DEFAULT_ROLE = EASM_AGENT365_READER DEFAULT_SECONDARY_ROLES = () "
            "RSA_PUBLIC_KEY = %s", (encoded,),
        )
        cursor.execute("DESCRIBE USER EASM_AGENT365_SERVICE")
        properties = {row[0]: row[1] for row in cursor.fetchall()}
        if properties.get("RSA_PUBLIC_KEY_FP") != fingerprint or properties.get("TYPE") != "SERVICE":
            raise ValueError("Snowflake 등록 공개키와 로컬 RSA가 다릅니다. 기존 키를 자동 교체하지 않습니다.")
        for statement in (
            "GRANT USAGE ON DATABASE EASM_CONNECTED_DEMO TO ROLE EASM_AGENT365_READER",
            "GRANT USAGE ON SCHEMA EASM_CONNECTED_DEMO.AGENTS TO ROLE EASM_AGENT365_READER",
            "GRANT MONITOR ON AGENT EASM_CONNECTED_DEMO.AGENTS.EASM_CORTEX_SAMPLE TO ROLE EASM_AGENT365_READER",
            "GRANT ROLE EASM_AGENT365_READER TO USER EASM_AGENT365_SERVICE",
        ):
            cursor.execute(statement)
