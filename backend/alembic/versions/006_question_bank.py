"""Extend questions and test cases for the Question Bank; add provenance and LLM lineage tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006_question_bank"
down_revision: Union[str, None] = "005_authentication"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    uuid_type = sa.Uuid(as_uuid=True)

    # ── questions: new Question Bank metadata columns ────────────────────────
    op.add_column("questions", sa.Column("status", sa.String(20), nullable=False, server_default="draft"))
    op.add_column("questions", sa.Column("input_format", sa.Text(), nullable=True))
    op.add_column("questions", sa.Column("output_format", sa.Text(), nullable=True))
    op.add_column("questions", sa.Column("constraints_text", sa.Text(), nullable=True))
    op.add_column("questions", sa.Column("supported_languages", sa.JSON(), nullable=True))
    op.add_column("questions", sa.Column("starter_code", sa.Text(), nullable=True))
    op.create_index("ix_questions_status", "questions", ["status"])
    op.create_check_constraint(
        "ck_questions_status",
        "questions",
        "status IN ('draft', 'validated', 'approved', 'active', 'deprecated')",
    )

    # ── question_test_cases: classification columns ──────────────────────────
    op.add_column("question_test_cases", sa.Column("is_sample", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("question_test_cases", sa.Column("is_functional", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("question_test_cases", sa.Column("tc_order", sa.Integer(), nullable=True))

    # ── question_provenance ──────────────────────────────────────────────────
    op.create_table(
        "question_provenance",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("question_id", uuid_type, nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("platform", sa.String(30), nullable=True),
        sa.Column("original_question_id", sa.String(100), nullable=True),
        sa.Column("contest_id", sa.String(100), nullable=True),
        sa.Column("contest_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("license", sa.Text(), nullable=True),
        sa.Column("dataset_name", sa.String(100), nullable=True),
        sa.Column("dataset_version", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", name="uq_question_provenance_question_id"),
    )
    op.create_index(
        "ix_question_provenance_question_id",
        "question_provenance",
        ["question_id"],
    )
    op.create_index(
        "ix_question_provenance_source",
        "question_provenance",
        ["source", "platform", "original_question_id"],
    )

    # ── question_llm_lineage ─────────────────────────────────────────────────
    op.create_table(
        "question_llm_lineage",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("question_id", uuid_type, nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("generation_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parent_question_id", uuid_type, nullable=True),
        sa.Column("generation_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_question_id"],
            ["questions.id"],
            ondelete="SET NULL",
            name="fk_question_llm_lineage_parent",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", name="uq_question_llm_lineage_question_id"),
    )
    op.create_index(
        "ix_question_llm_lineage_question_id",
        "question_llm_lineage",
        ["question_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_question_llm_lineage_question_id", table_name="question_llm_lineage")
    op.drop_table("question_llm_lineage")

    op.drop_index("ix_question_provenance_source", table_name="question_provenance")
    op.drop_index("ix_question_provenance_question_id", table_name="question_provenance")
    op.drop_table("question_provenance")

    op.drop_column("question_test_cases", "tc_order")
    op.drop_column("question_test_cases", "is_functional")
    op.drop_column("question_test_cases", "is_sample")

    op.drop_constraint("ck_questions_status", "questions", type_="check")
    op.drop_index("ix_questions_status", table_name="questions")
    op.drop_column("questions", "starter_code")
    op.drop_column("questions", "supported_languages")
    op.drop_column("questions", "constraints_text")
    op.drop_column("questions", "output_format")
    op.drop_column("questions", "input_format")
    op.drop_column("questions", "status")
