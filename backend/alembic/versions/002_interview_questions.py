"""Add ordered interview question assignments."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_interview_questions"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    uuid_type = sa.Uuid(as_uuid=True)
    op.create_table(
        "interview_questions",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("interview_session_id", uuid_type, nullable=False),
        sa.Column("question_id", uuid_type, nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["interview_session_id"],
            ["interview_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "interview_session_id",
            "question_id",
            name="uq_interview_questions_session_question",
        ),
        sa.UniqueConstraint(
            "interview_session_id",
            "sequence_number",
            name="uq_interview_questions_session_sequence",
        ),
    )
    op.create_index(
        "ix_interview_questions_interview_session_id",
        "interview_questions",
        ["interview_session_id"],
    )
    op.create_index(
        "ix_interview_questions_question_id",
        "interview_questions",
        ["question_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interview_questions_question_id", table_name="interview_questions"
    )
    op.drop_index(
        "ix_interview_questions_interview_session_id",
        table_name="interview_questions",
    )
    op.drop_table("interview_questions")
