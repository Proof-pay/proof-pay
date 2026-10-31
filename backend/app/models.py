# SQLModel needs quoted forward relationships with this repository's mapper setup.
# ruff: noqa: UP037, UP045
import secrets
import uuid
from datetime import UTC, datetime
from typing import Optional

from pydantic import EmailStr
from sqlalchemy import BigInteger, DateTime, Index, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


def generate_public_token() -> str:
    return secrets.token_urlsafe(32)


# ==========================================
# USER MODELS
# ==========================================


class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str | None = Field(default=None)
    google_id: str | None = Field(default=None, unique=True, index=True, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=512)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )

    items: list["Item"] = Relationship(back_populates="owner", cascade_delete=True)
    merchant: Optional["Merchant"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"uselist": False},
        cascade_delete=True,
    )

    @property
    def has_password(self) -> bool:
        return bool(self.hashed_password)

    @property
    def google_linked(self) -> bool:
        return bool(self.google_id)


class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None
    avatar_url: str | None = None
    has_password: bool = True
    google_linked: bool = False


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# ==========================================
# MERCHANT MODELS
# ==========================================


class MerchantBase(SQLModel):
    business_name: str = Field(max_length=255)


class MerchantCreate(MerchantBase):
    pass


class MerchantUpdate(SQLModel):
    business_name: str | None = Field(default=None, max_length=255)


class Merchant(MerchantBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id",
        unique=True,
        index=True,
        nullable=False,
        ondelete="CASCADE",
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=50)
    receiving_address: str | None = Field(default=None, max_length=255)
    network: str = Field(default="mainnet", max_length=20)
    default_expiry_hours: int = Field(default=24)
    required_confirmations: int = Field(default=1)

    user: User | None = Relationship(back_populates="merchant")
    invoices: list["Invoice"] = Relationship(
        back_populates="merchant", cascade_delete=True
    )


class MerchantPublic(MerchantBase):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime


class MerchantsPublic(SQLModel):
    data: list[MerchantPublic]
    count: int


# ==========================================
# INVOICE MODELS
# ==========================================


class InvoiceBase(SQLModel):
    order_reference: str = Field(max_length=255)
    description: str | None = Field(default=None, sa_type=Text)
    network: str = Field(max_length=50)
    receiving_address: str = Field(max_length=255)
    expected_amount_sats: int = Field(sa_type=BigInteger)
    required_confirmations: int = Field(default=1)
    status: str = Field(default="pending", max_length=50)
    expires_at: datetime = Field(sa_type=DateTime(timezone=True))


class InvoiceCreate(InvoiceBase):
    pass


class InvoiceUpdate(SQLModel):
    order_reference: str | None = Field(default=None, max_length=255)
    description: str | None = None
    status: str | None = Field(default=None, max_length=50)
    required_confirmations: int | None = None
    expires_at: datetime | None = None


class Invoice(InvoiceBase, table=True):
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "idempotency_key", name="uq_invoice_merchant_idempotency"
        ),
        Index("ix_invoice_merchant_status", "merchant_id", "status"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    merchant_id: uuid.UUID = Field(
        foreign_key="merchant.id", index=True, nullable=False, ondelete="CASCADE"
    )
    public_token: str = Field(
        default_factory=generate_public_token, unique=True, index=True, max_length=255
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    title: str = Field(default="", max_length=255)
    payment_status: str = Field(default="pending", max_length=30)
    issued_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    fiat_reference_amount: str | None = Field(default=None, max_length=40)
    fiat_currency: str | None = Field(default=None, max_length=3)
    idempotency_key: str | None = Field(default=None, max_length=128)
    scan_attempted_at: datetime | None = Field(default=None)
    last_scanned_at: datetime | None = Field(default=None)
    watched_at: datetime | None = Field(default=None)
    idempotency_hash: str | None = Field(default=None, max_length=64)

    merchant: Merchant | None = Relationship(back_populates="invoices")
    payment_outputs: list["PaymentOutput"] = Relationship(
        back_populates="invoice", cascade_delete=True
    )
    receipt: Optional["Receipt"] = Relationship(
        back_populates="invoice",
        sa_relationship_kwargs={"uselist": False},
        cascade_delete=True,
    )


class AddressReservation(SQLModel, table=True):
    """Permanent merchant association, retained after invoice edits/deletion.

    A null merchant blocks reuse where historical ownership is unknown/ambiguous.
    invoice_id retains the original historical association, without a foreign key.
    """

    __tablename__ = "address_reservation"
    __table_args__ = (
        UniqueConstraint("network", "address", name="uq_reserved_destination"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    network: str = Field(max_length=20)
    address: str = Field(max_length=255)
    invoice_id: uuid.UUID = Field(index=True)
    merchant_id: uuid.UUID | None = Field(default=None, index=True)
    auto_allocate: bool = Field(default=False)
    created_at: datetime = Field(default_factory=get_datetime_utc)


class DetectedOutput(SQLModel, table=True):
    """Verified observation only; never included in invoice accounting."""

    __tablename__ = "detected_output"
    __table_args__ = (
        UniqueConstraint("network", "txid", "vout", name="uq_detected_output"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    network: str = Field(max_length=20)
    address: str = Field(max_length=255, index=True)
    txid: str = Field(max_length=64)
    vout: int
    amount_sats: int = Field(sa_type=BigInteger)
    confirmations: int
    last_checked_at: datetime = Field(default_factory=get_datetime_utc)


class InvoicePublic(InvoiceBase):
    id: uuid.UUID
    merchant_id: uuid.UUID
    public_token: str
    created_at: datetime


class InvoicesPublic(SQLModel):
    data: list[InvoicePublic]
    count: int


# ==========================================
# PAYMENT OUTPUT MODELS
# ==========================================


class PaymentOutputBase(SQLModel):
    network: str = Field(max_length=50)
    txid: str = Field(index=True, max_length=255)
    vout: int
    amount_sats: int = Field(sa_type=BigInteger)
    status: str = Field(max_length=50)
    confirmations: int = Field(default=0)
    first_seen_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    last_checked_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


class PaymentOutputCreate(PaymentOutputBase):
    invoice_id: uuid.UUID


class PaymentOutputUpdate(SQLModel):
    status: str | None = Field(default=None, max_length=50)
    confirmations: int | None = None
    last_checked_at: datetime | None = None


class PaymentOutput(PaymentOutputBase, table=True):
    __tablename__ = "payment_output"
    __table_args__ = (
        UniqueConstraint(
            "network", "txid", "vout", name="uq_payment_output_network_txid_vout"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    invoice_id: uuid.UUID = Field(
        foreign_key="invoice.id", index=True, nullable=False, ondelete="CASCADE"
    )
    last_attempted_at: datetime | None = Field(default=None)
    is_late: bool = Field(default=False)

    invoice: Invoice | None = Relationship(back_populates="payment_outputs")


class PaymentOutputPublic(PaymentOutputBase):
    id: uuid.UUID
    invoice_id: uuid.UUID


class PaymentOutputsPublic(SQLModel):
    data: list[PaymentOutputPublic]
    count: int


# ==========================================
# RECEIPT MODELS
# ==========================================


class ReceiptBase(SQLModel):
    issued_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


class ReceiptCreate(ReceiptBase):
    invoice_id: uuid.UUID


class ReceiptUpdate(SQLModel):
    public_token: str | None = Field(default=None, max_length=255)
    issued_at: datetime | None = None


class Receipt(ReceiptBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    invoice_id: uuid.UUID = Field(
        foreign_key="invoice.id",
        unique=True,
        index=True,
        nullable=False,
        ondelete="CASCADE",
    )
    public_token: str = Field(
        default_factory=generate_public_token, unique=True, index=True, max_length=255
    )
    reference: str = Field(
        default_factory=lambda: f"PP-{secrets.token_hex(8).upper()}",
        unique=True,
        index=True,
        max_length=32,
    )
    invoice_reference: str = Field(default="", max_length=255)
    merchant_name: str = Field(default="", max_length=255)
    amount_sats: int = Field(default=0, sa_type=BigInteger)
    network: str = Field(default="mainnet", max_length=20)
    required_confirmations: int = Field(default=1)
    output_refs: str = Field(default="[]", sa_type=Text)

    invoice: Invoice | None = Relationship(back_populates="receipt")


class ReceiptPublic(ReceiptBase):
    id: uuid.UUID
    invoice_id: uuid.UUID
    public_token: str


class ReceiptsPublic(SQLModel):
    data: list[ReceiptPublic]
    count: int


# ==========================================
# ITEM MODELS & AUTH SCHEMAS
# ==========================================


class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


class ItemCreate(ItemBase):
    pass


class ItemUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


class Message(SQLModel):
    message: str


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
