import re
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.payments.chain import bch_to_sats


class MerchantSettings(BaseModel):
    business_name: str = Field(min_length=1, max_length=255)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=50)
    receiving_address: str | None = None
    network: Literal["mainnet", "testnet", "chipnet", "regtest"]
    default_expiry_hours: int = Field(ge=1, le=24 * 90)
    required_confirmations: int = Field(ge=1, le=100)


class MerchantPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_name: str | None = Field(default=None, min_length=1, max_length=255)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=50)
    receiving_address: str | None = None
    default_expiry_hours: int | None = Field(default=None, ge=1, le=24 * 90)
    required_confirmations: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def required_values(self) -> Self:
        for name in ("business_name", "default_expiry_hours", "required_confirmations"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class InvoiceCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_reference: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    amount_bch: str
    receiving_address: str | None = None
    expires_at: AwareDatetime | None = None
    fiat_reference_amount: str | None = Field(default=None, max_length=40)
    fiat_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @field_validator("amount_bch")
    @classmethod
    def valid_amount(cls, value: str) -> str:
        if not re.fullmatch(r"\d+(?:\.\d{1,8})?", value):
            raise ValueError("Use a plain BCH decimal with at most eight places")
        bch_to_sats(value)
        return value

    @field_validator("fiat_reference_amount")
    @classmethod
    def valid_fiat(cls, value: str | None) -> str | None:
        if value is not None and (
            not re.fullmatch(r"\d+(?:\.\d{1,8})?", value) or Decimal(value) <= 0
        ):
            raise ValueError("Fiat reference amount must be a positive decimal")
        return value

    @model_validator(mode="after")
    def fiat_pair(self) -> Self:
        if bool(self.fiat_reference_amount) != bool(self.fiat_currency):
            raise ValueError(
                "Fiat reference amount and currency must be supplied together"
            )
        return self


class InvoicePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_reference: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    amount_bch: str | None = None
    receiving_address: str | None = None
    expires_at: AwareDatetime | None = None
    fiat_reference_amount: str | None = Field(default=None, max_length=40)
    fiat_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def required_values(self) -> Self:
        for name in (
            "order_reference",
            "title",
            "amount_bch",
            "receiving_address",
            "expires_at",
        ):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    @field_validator("amount_bch")
    @classmethod
    def valid_amount(cls, value: str | None) -> str | None:
        if value is not None:
            if not re.fullmatch(r"\d+(?:\.\d{1,8})?", value):
                raise ValueError("Use a plain BCH decimal with at most eight places")
            bch_to_sats(value)
        return value

    @field_validator("fiat_reference_amount")
    @classmethod
    def valid_fiat(cls, value: str | None) -> str | None:
        return InvoiceCreateInput.valid_fiat(value)


class ClaimInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vouts: list[int] = Field(min_length=1, max_length=100)

    @field_validator("vouts")
    @classmethod
    def distinct_vouts(cls, value: list[int]) -> list[int]:
        if any(v < 0 for v in value) or len(set(value)) != len(value):
            raise ValueError("Output indexes must be distinct nonnegative integers")
        return value


class PaymentView(BaseModel):
    id: UUID
    invoice_id: UUID
    network: str
    txid: str
    vout: int
    amount_sats: int
    confirmations: int
    status: str
    is_late: bool
    first_seen_at: datetime
    last_checked_at: datetime


class InvoiceView(BaseModel):
    id: UUID
    order_reference: str
    title: str
    description: str | None
    network: str
    receiving_address: str
    expected_amount_sats: int
    amount_bch: str
    required_confirmations: int
    status: str
    payment_status: str
    received_amount_sats: int
    confirmed_amount_sats: int
    expires_at: datetime
    issued_at: datetime | None
    created_at: datetime
    updated_at: datetime
    fiat_reference_amount: str | None
    fiat_currency: str | None
    public_token: str
    checkout_url: str
    payment_uri: str | None
    receipt_token: str | None
    verification_stale: bool
    payments: list[PaymentView]


class PublicCheckout(BaseModel):
    amount_due_bch: str
    required_confirmations: int
    late_amount_sats: int
    overpaid_amount_sats: int
    merchant_name: str
    title: str
    description: str | None
    order_reference: str
    network: str
    amount_bch: str
    expected_amount_sats: int
    receiving_address: str
    expires_at: datetime
    status: str
    payment_status: str
    payment_uri: str | None
    qr_payload: str | None
    received_amount_sats: int
    confirmed_amount_sats: int
    receipt_url: str | None
    verification_stale: bool


class PublicPayment(BaseModel):
    network: str
    txid: str
    vout: int
    amount_sats: int
    confirmations: int
    status: str
    is_late: bool
    last_checked_at: datetime


class PublicReceipt(BaseModel):
    requested_amount_sats: int
    receiving_address: str
    payments: list[PublicPayment]
    reference: str
    invoice_reference: str
    merchant_name: str
    amount_sats: int
    network: str
    required_confirmations: int
    output_refs: list[str]
    issued_at: datetime
    verified_at: datetime | None
    missing_output_refs: list[str] = Field(default_factory=list)
    invoice_payment_status: str = "unavailable"
    verification_url: str
    current_status: str
    verification_stale: bool
    statement: str = "Observed BCH payment against this request; does not establish delivery or payer identity."


class ReceiptView(PublicReceipt):
    id: UUID
    public_token: str


class InvoicePage(BaseModel):
    data: list[InvoiceView]
    count: int


class PaymentPage(BaseModel):
    data: list[PaymentView]
    count: int


class ReceiptPage(BaseModel):
    data: list[ReceiptView]
    count: int


class DashboardSummary(BaseModel):
    network: str
    currency: Literal["BCH"] = "BCH"
    confirmed_received_sats: int
    outstanding_requested_sats: int
    request_counts: dict[str, int]
    recent_activity: list[InvoiceView]


class PaymentHistoryPage(PaymentPage):
    network: str
    currency: Literal["BCH"] = "BCH"
