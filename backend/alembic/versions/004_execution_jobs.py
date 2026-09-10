"""Add durable local execution jobs."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004_execution_jobs"
down_revision: Union[str, None] = "003_evaluation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    uuid_type = sa.Uuid(as_uuid=True)
    op.create_table(
        "execution_jobs",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("submission_id", uuid_type, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["submissions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id"),
    )
    op.create_index(
        "ix_execution_jobs_submission_id", "execution_jobs", ["submission_id"]
    )
    op.create_index("ix_execution_jobs_status", "execution_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_execution_jobs_status", table_name="execution_jobs")
    op.drop_index("ix_execution_jobs_submission_id", table_name="execution_jobs")
    op.drop_table("execution_jobs")
