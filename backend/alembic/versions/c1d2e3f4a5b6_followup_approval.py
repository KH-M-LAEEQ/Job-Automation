"""follow-up drafts require approval; bounded cadence

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f123
Create Date: 2026-10-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b7c8d9e0f123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('followups', sa.Column('recipient', sa.String(length=255), nullable=True))
    op.add_column('followups', sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True))
    # Clamp existing cadence settings into the new validated bounds.
    op.execute('UPDATE users SET followup_first_days = GREATEST(LEAST(followup_first_days, 60), 2)')
    op.execute('UPDATE users SET followup_interval_days = GREATEST(LEAST(followup_interval_days, 60), 3)')
    op.execute('UPDATE users SET followup_max_count = GREATEST(LEAST(followup_max_count, 3), 0)')


def downgrade() -> None:
    op.drop_column('followups', 'decided_at')
    op.drop_column('followups', 'recipient')
