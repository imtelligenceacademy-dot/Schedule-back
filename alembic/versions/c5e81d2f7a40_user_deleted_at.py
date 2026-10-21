"""Mark deleted user accounts while keeping their history.

Revision ID: c5e81d2f7a40
Revises: b21890cf50a1
"""

from alembic import op
import sqlalchemy as sa

revision = "c5e81d2f7a40"
down_revision = "b21890cf50a1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("deleted_at")
