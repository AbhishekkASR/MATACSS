"""Persist structured assessment feedback per submission."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007_assessment_feedback"
down_revision: Union[str, None] = "006_question_bank"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assessment_feedback",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("submission_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("failure_kind", sa.String(length=40), nullable=True),
        sa.Column("interviewer_feedback", sa.JSON(), nullable=True),
        sa.Column("reviewer_feedback", sa.JSON(), nullable=True),
        sa.Column("edge_case_feedback", sa.JSON(), nullable=True),
        sa.Column("aggregated_feedback", sa.JSON(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_assessment_feedback_status",
        ),
    )
    op.create_index(
        "ix_assessment_feedback_submission_id",
        "assessment_feedback",
        ["submission_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assessment_feedback_submission_id", table_name="assessment_feedback"
    )
    op.drop_table("assessment_feedback")
