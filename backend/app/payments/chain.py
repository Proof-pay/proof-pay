"""CashAddr validation and read-only Bitcoin Cash Node RPC."""

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import settings

ALPHABET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
PREFIXES = {"mainnet": "bitcoincash", "testnet": "bchtest", "regtest": "bchreg"}


def _polymod(values: list[int]) -> int:
    c = 1
    for value in values:
        c0 = c >> 35
        c = ((c & 0x07FFFFFFFF) << 5) ^ value
        for bit, generator in enumerate(
            (0x98F2BC8E61, 0x79B76D99E2, 0xF33E5FB3C4, 0xAE2EABE2A8, 0x1E4F43E470)
        ):
            if (c0 >> bit) & 1:
                c ^= generator
    return c ^ 1


def normalize_address(value: str, network: str) -> str:
    prefix = PREFIXES[network]
    if value.lower() != value and value.upper() != value:
        raise ValueError("Mixed case CashAddr is invalid")
    value = value.lower()
    if ":" not in value:
        value = f"{prefix}:{value}"
    parts = value.split(":")
    if len(parts) != 2 or parts[0] != prefix or len(parts[1]) < 8:
        raise ValueError("CashAddr network does not match")
    try:
        data = [ALPHABET.index(char) for char in parts[1]]
    except ValueError as exc:
        raise ValueError("Invalid CashAddr characters") from exc
    if _polymod([ord(c) & 31 for c in prefix] + [0] + data) != 0:
        raise ValueError("Invalid CashAddr checksum")
    payload = data[:-8]
    acc = bits = 0
    decoded = bytearray()
    for digit in payload:
        acc = (acc << 5) | digit
        bits += 5
        if bits >= 8:
            bits -= 8
            decoded.append((acc >> bits) & 255)
    if not decoded or bits >= 5 or ((acc << (8 - bits)) & 255):
        raise ValueError("Invalid CashAddr padding")
    version = decoded[0]
    hash_sizes = (20, 24, 28, 32, 40, 48, 56, 64)
    if (
        version & 128
        or (version >> 3) not in (0, 1)
        or len(decoded) - 1 != hash_sizes[version & 7]
    ):
        raise ValueError("Invalid CashAddr version")
    return value


def address_script_hex(value: str, network: str) -> str:
    """Standard P2PKH/P2SH locking script for a checked CashAddr."""
    normalized = normalize_address(value, network)
    payload = [ALPHABET.index(char) for char in normalized.split(":", 1)[1]][:-8]
    acc = bits = 0
    decoded = bytearray()
    for digit in payload:
        acc = (acc << 5) | digit
        bits += 5
        if bits >= 8:
            bits -= 8
            decoded.append((acc >> bits) & 255)
    version, hash_bytes = decoded[0], bytes(decoded[1:])
    push = f"{len(hash_bytes):02x}{hash_bytes.hex()}"
    return f"76a9{push}88ac" if version >> 3 == 0 else f"a9{push}87"


def bch_to_sats(value: str | Decimal) -> int:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid BCH amount") from exc
    sats = amount * 100_000_000
    if (
        not amount.is_finite()
        or amount <= 0
        or sats != sats.to_integral_value()
        or sats > 2_100_000_000_000_000
    ):
        raise ValueError(
            "BCH amount must be positive with at most eight decimal places"
        )
    return int(sats)


def sats_to_bch(sats: int) -> str:
    return format(Decimal(sats) / Decimal(100_000_000), "f")


class ProviderError(Exception):
    pass


class TransactionNotFound(ProviderError):
    pass


class BCHNodeProvider:
    """Read-only JSON-RPC adapter. Requires txindex for old arbitrary claims."""

    def __init__(
        self,
        url: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        self.url = url or settings.BCH_RPC_URL
        self.user = user if user is not None else settings.BCH_RPC_USER
        self.password = password if password is not None else settings.BCH_RPC_PASSWORD

    def _call(self, method: str, params: list[Any] | None = None) -> dict[str, Any]:
        if not self.url:
            raise ProviderError("BCH RPC is not configured")
        auth = (self.user, self.password or "") if self.user else None
        try:
            with httpx.Client(timeout=8, auth=auth) as client:
                response = client.post(
                    self.url,
                    json={
                        "jsonrpc": "1.0",
                        "id": "proofpay",
                        "method": method,
                        "params": params or [],
                    },
                )
                response.raise_for_status()
                data = response.json(parse_float=Decimal)
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(
                "BCH provider unavailable or returned invalid data"
            ) from exc
        if (
            data.get("error")
            and method == "getrawtransaction"
            and data["error"].get("code") == -5
        ):
            raise TransactionNotFound("Transaction not found by BCH node")
        if data.get("error"):
            raise ProviderError(f"BCH RPC {method} failed")
        result = data.get("result")
        if not isinstance(result, dict):
            raise ProviderError("Invalid BCH RPC result")
        return result

    def transaction(self, txid: str, network: str) -> dict[str, Any]:
        info = self._call("getblockchaininfo")
        chain = info.get("chain")
        expected = {"mainnet": "main", "testnet": "test", "regtest": "regtest"}[network]
        if chain != expected:
            raise ProviderError("BCH provider network mismatch")
        if info.get("initialblockdownload") is True:
            raise ProviderError("BCH node is still syncing")
        tx = self._call("getrawtransaction", [txid, 1])
        if tx.get("txid", "").lower() != txid.lower() or not isinstance(
            tx.get("vout"), list
        ):
            raise ProviderError("BCH provider returned a different transaction")
        return tx
