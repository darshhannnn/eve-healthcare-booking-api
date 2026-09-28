"""Initial schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-09-28 19:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=120), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=10), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='uq_users_email')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # Diagnostic centres table
    op.create_table(
        'diagnostic_centres',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('location', sa.String(length=200), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_diagnostic_centres_name'), 'diagnostic_centres', ['name'], unique=False)

    # Diagnostic tests table
    op.create_table(
        'diagnostic_tests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_diagnostic_tests_code')
    )
    op.create_index(op.f('ix_diagnostic_tests_code'), 'diagnostic_tests', ['code'], unique=True)

    # Centre offerings table
    op.create_table(
        'centre_offerings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('centre_id', sa.Integer(), nullable=False),
        sa.Column('test_id', sa.Integer(), nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['centre_id'], ['diagnostic_centres.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['test_id'], ['diagnostic_tests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('centre_id', 'test_id', name='uq_centre_offering')
    )
    op.create_index(op.f('ix_centre_offerings_centre_id'), 'centre_offerings', ['centre_id'], unique=False)
    op.create_index(op.f('ix_centre_offerings_test_id'), 'centre_offerings', ['test_id'], unique=False)

    # Bookings table
    op.create_table(
        'bookings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('centre_id', sa.Integer(), nullable=False),
        sa.Column('test_id', sa.Integer(), nullable=False),
        sa.Column('appointment_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('idempotency_key', sa.String(length=120), nullable=True),
        sa.Column('request_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['centre_id'], ['diagnostic_centres.id']),
        sa.ForeignKeyConstraint(['test_id'], ['diagnostic_tests.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_bookings_user_idempotency')
    )
    op.create_index(op.f('ix_bookings_user_id'), 'bookings', ['user_id'], unique=False)
    op.create_index(op.f('ix_bookings_centre_id'), 'bookings', ['centre_id'], unique=False)
    op.create_index(op.f('ix_bookings_test_id'), 'bookings', ['test_id'], unique=False)
    op.create_index(op.f('ix_bookings_status'), 'bookings', ['status'], unique=False)
    op.create_index('ix_bookings_user_status', 'bookings', ['user_id', 'status'], unique=False)

    # Partial unique index for duplicate-slot prevention (PostgreSQL only)
    # Skip this on SQLite as it doesn't support partial indexes
    try:
        op.create_index(
            'uq_bookings_active_slot',
            'bookings',
            ['user_id', 'centre_id', 'test_id', 'appointment_at'],
            unique=True,
            postgresql_where=sa.text("status != 'CANCELLED'")
        )
    except Exception:
        # Skip on SQLite/dialects that don't support partial indexes
        pass

    # Payments table
    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('booking_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('provider_reference', sa.String(length=64), nullable=False),
        sa.Column('idempotency_key', sa.String(length=120), nullable=True),
        sa.Column('request_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['booking_id'], ['bookings.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider_reference', name='uq_payments_provider_reference'),
        sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_payments_user_idempotency')
    )
    op.create_index(op.f('ix_payments_user_id'), 'payments', ['user_id'], unique=False)
    op.create_index(op.f('ix_payments_booking_id'), 'payments', ['booking_id'], unique=False)
    op.create_index(op.f('ix_payments_status'), 'payments', ['status'], unique=False)

    # Webhook events table
    op.create_table(
        'webhook_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(length=120), nullable=False),
        sa.Column('payment_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('detail', sa.String(length=255), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', name='uq_webhook_events_event_id')
    )
    op.create_index(op.f('ix_webhook_events_event_id'), 'webhook_events', ['event_id'], unique=True)
    op.create_index(op.f('ix_webhook_events_status'), 'webhook_events', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_webhook_events_status'), table_name='webhook_events')
    op.drop_index(op.f('ix_webhook_events_event_id'), table_name='webhook_events')
    op.drop_table('webhook_events')

    op.drop_index(op.f('ix_payments_status'), table_name='payments')
    op.drop_index(op.f('ix_payments_booking_id'), table_name='payments')
    op.drop_index(op.f('ix_payments_user_id'), table_name='payments')
    op.drop_table('payments')

    # Drop partial index if it exists (PostgreSQL only)
    try:
        op.drop_index('uq_bookings_active_slot', table_name='bookings')
    except Exception:
        # Skip on SQLite/dialects that don't support partial indexes
        pass

    op.drop_index(op.f('ix_bookings_status'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_test_id'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_centre_id'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_user_id'), table_name='bookings')
    op.drop_index('ix_bookings_user_status', table_name='bookings')
    op.drop_table('bookings')

    op.drop_index(op.f('ix_centre_offerings_test_id'), table_name='centre_offerings')
    op.drop_index(op.f('ix_centre_offerings_centre_id'), table_name='centre_offerings')
    op.drop_table('centre_offerings')

    op.drop_index(op.f('ix_diagnostic_tests_code'), table_name='diagnostic_tests')
    op.drop_table('diagnostic_tests')

    op.drop_index(op.f('ix_diagnostic_centres_name'), table_name='diagnostic_centres')
    op.drop_table('diagnostic_centres')

    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
