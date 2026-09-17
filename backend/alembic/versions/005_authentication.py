"""Add authenticated user records and tie candidates to users."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005_authentication"
down_revision: Union[str, None] = "004_execution_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    uuid_type = sa.Uuid(as_uuid=True)
    op.create_table(
        "users",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="candidate"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.add_column("candidates", sa.Column("user_id", uuid_type, nullable=True))
    op.create_index("ix_candidates_user_id", "candidates", ["user_id"], unique=False)
    op.create_foreign_key(
        "fk_candidates_user_id_users",
        "candidates",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_candidates_user_id_users", "candidates", type_="foreignkey")
    op.drop_index("ix_candidates_user_id", table_name="candidates")
    op.drop_column("candidates", "user_id")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
