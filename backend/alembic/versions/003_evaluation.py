"""Add deterministic question test cases and evaluation results."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003_evaluation"
down_revision: Union[str, None] = "002_interview_questions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    uuid_type = sa.Uuid(as_uuid=True)
    op.create_table(
        "question_test_cases",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("question_id", uuid_type, nullable=False),
        sa.Column("stdin", sa.Text(), nullable=False),
        sa.Column("expected_stdout", sa.Text(), nullable=False),
        sa.Column("time_limit_ms", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_question_test_cases_question_id",
        "question_test_cases",
        ["question_id"],
    )
    op.create_table(
        "evaluation_results",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("submission_id", uuid_type, nullable=False),
        sa.Column("total_test_cases", sa.Integer(), nullable=False),
        sa.Column("passed_test_cases", sa.Integer(), nullable=False),
        sa.Column("failed_test_cases", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("case_results", sa.JSON(), nullable=False),
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
        "ix_evaluation_results_submission_id",
        "evaluation_results",
        ["submission_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evaluation_results_submission_id", table_name="evaluation_results"
    )
    op.drop_table("evaluation_results")
    op.drop_index(
        "ix_question_test_cases_question_id", table_name="question_test_cases"
    )
    op.drop_table("question_test_cases")
