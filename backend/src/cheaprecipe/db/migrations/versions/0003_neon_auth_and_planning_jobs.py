"""Neon Auth accounts, and planning jobs in the database

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('user_account', schema=None) as batch_op:
        batch_op.add_column(sa.Column('auth_user_id', sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint('uq_user_account_auth_user_id', ['auth_user_id'])
        batch_op.alter_column('password_hash', existing_type=sa.String(length=255), nullable=True)

    op.create_table(
        'planning_job',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('steps', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('error_status', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('planning_job', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_planning_job_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('planning_job', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_planning_job_user_id'))
    op.drop_table('planning_job')

    with op.batch_alter_table('user_account', schema=None) as batch_op:
        batch_op.alter_column('password_hash', existing_type=sa.String(length=255), nullable=False)
        batch_op.drop_constraint('uq_user_account_auth_user_id', type_='unique')
        batch_op.drop_column('auth_user_id')
