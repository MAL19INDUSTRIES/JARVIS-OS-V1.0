"""Create hosted multi-tenant persistence tables."""

from alembic import op
import sqlalchemy as sa


revision = "20260813_0001"
down_revision = None
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "user_secrets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_user_secret_name"),
    )
    op.create_index("ix_user_secrets_user_id", "user_secrets", ["user_id"])

    op.create_table(
        "memory_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "category", "key", name="uq_memory_user_category_key"),
    )
    op.create_index("ix_memory_entries_user_id", "memory_entries", ["user_id"])

    op.create_table(
        "user_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "namespace", "key", name="uq_user_config_key"),
    )
    op.create_index("ix_user_configs_user_id", "user_configs", ["user_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"])
    op.create_index("ix_chat_user_created", "chat_messages", ["user_id", "created_at"])

    op.create_table(
        "task_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(80), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("saved_file", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_records_user_id", "task_records", ["user_id"])
    op.create_index("ix_task_records_task_id", "task_records", ["task_id"])
    op.create_index("ix_task_user_created", "task_records", ["user_id", "created_at"])

    op.create_table(
        "answer_cache_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("normalized_question", sa.String(260), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "normalized_question", name="uq_answer_user_question"),
    )
    op.create_index("ix_answer_cache_entries_user_id", "answer_cache_entries", ["user_id"])


def downgrade() -> None:
    op.drop_table("answer_cache_entries")
    op.drop_table("task_records")
    op.drop_table("chat_messages")
    op.drop_table("user_configs")
    op.drop_table("memory_entries")
    op.drop_table("user_secrets")
    op.drop_table("users")
