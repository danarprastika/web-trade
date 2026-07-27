"""Add paper trading tables: strategies, orders, positions, trades, risk_profiles

Revision ID: 003_add_paper_trading
Revises: 002_add_oauth_and_watchlist
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003_add_paper_trading"
down_revision: str | None = "002_add_oauth_and_watchlist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("strategy_type", sa.String(50), nullable=False),
        sa.Column("parameters", sa.String(500), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="stopped"),
        sa.Column("short_window", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("long_window", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("is_running", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_strategies_user_id", "strategies", ["user_id"])
    op.create_index("ix_strategies_asset_id", "strategies", ["asset_id"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("trading_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "strategy_id",
            sa.Integer(),
            sa.ForeignKey("strategies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("order_type", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
        sa.Column("price", sa.Numeric(18, 8), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("filled_quantity", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_account_id", "orders", ["account_id"])
    op.create_index("ix_orders_asset_id", "orders", ["asset_id"])
    op.create_index("ix_orders_strategy_id", "orders", ["strategy_id"])
    op.create_index("ix_orders_idempotency_key", "orders", ["idempotency_key"], unique=True)

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("trading_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
        sa.Column("avg_entry_price", sa.Numeric(18, 8), nullable=False),
        sa.Column("current_price", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("is_open", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_positions_user_id", "positions", ["user_id"])
    op.create_index("ix_positions_account_id", "positions", ["account_id"])
    op.create_index("ix_positions_asset_id", "positions", ["asset_id"])

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("trading_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
        sa.Column("price", sa.Numeric(18, 8), nullable=False),
        sa.Column("fee", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("pnl", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_trades_user_id", "trades", ["user_id"])
    op.create_index("ix_trades_account_id", "trades", ["account_id"])
    op.create_index("ix_trades_order_id", "trades", ["order_id"])
    op.create_index("ix_trades_asset_id", "trades", ["asset_id"])

    op.create_table(
        "risk_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("trading_accounts.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("daily_loss_limit", sa.Numeric(18, 2), nullable=False, server_default="1000"),
        sa.Column("max_drawdown", sa.Numeric(18, 2), nullable=False, server_default="0.2"),
        sa.Column("position_limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("exposure_limit", sa.Numeric(18, 2), nullable=False, server_default="50000"),
        sa.Column(
            "kill_switch_active", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "circuit_breaker_triggered",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("circuit_breaker_reason", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_risk_profiles_user_id", "risk_profiles", ["user_id"])
    op.create_index("ix_risk_profiles_account_id", "risk_profiles", ["account_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_risk_profiles_account_id", table_name="risk_profiles")
    op.drop_index("ix_risk_profiles_user_id", table_name="risk_profiles")
    op.drop_table("risk_profiles")

    op.drop_index("ix_trades_asset_id", table_name="trades")
    op.drop_index("ix_trades_order_id", table_name="trades")
    op.drop_index("ix_trades_account_id", table_name="trades")
    op.drop_index("ix_trades_user_id", table_name="trades")
    op.drop_table("trades")

    op.drop_index("ix_positions_asset_id", table_name="positions")
    op.drop_index("ix_positions_account_id", table_name="positions")
    op.drop_index("ix_positions_user_id", table_name="positions")
    op.drop_table("positions")

    op.drop_index("ix_orders_idempotency_key", table_name="orders")
    op.drop_index("ix_orders_strategy_id", table_name="orders")
    op.drop_index("ix_orders_asset_id", table_name="orders")
    op.drop_index("ix_orders_account_id", table_name="orders")
    op.drop_index("ix_orders_user_id", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_strategies_asset_id", table_name="strategies")
    op.drop_index("ix_strategies_user_id", table_name="strategies")
    op.drop_table("strategies")
