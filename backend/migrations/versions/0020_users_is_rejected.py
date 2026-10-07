"""users.is_rejected: an admin rejected a pending self-signup (kept, never hard-deleted).

A rejected signup is an agent with no agent link and is no longer pending, so
ck_users_role_scope also allows that while is_rejected is true.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-03
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CK = "ck_users_role_scope"
OLD_SCOPE = ("(role = 'agent' AND (agent_id IS NOT NULL OR is_pending))"
             " OR (role = 'distributor' AND distributor_id IS NOT NULL)"
             " OR role = 'admin'")
NEW_SCOPE = ("(role = 'agent' AND (agent_id IS NOT NULL OR is_pending OR is_rejected))"
             " OR (role = 'distributor' AND distributor_id IS NOT NULL)"
             " OR role = 'admin'")


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("is_rejected", sa.Boolean(), server_default=sa.false(),
                                   nullable=False))
        batch.drop_constraint(CK, type_="check")
        batch.create_check_constraint(CK, NEW_SCOPE)


def downgrade() -> None:
    # A rejected signup's own audit rows (its signup) keep their entry without the user link.
    op.execute("UPDATE audit_log SET user_id = NULL "
               "WHERE user_id IN (SELECT id FROM users WHERE is_rejected)")
    op.execute("DELETE FROM users WHERE is_rejected")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint(CK, type_="check")
        batch.create_check_constraint(CK, OLD_SCOPE)
        batch.drop_column("is_rejected")
