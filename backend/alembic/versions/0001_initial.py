"""initial schema

Creates the full domain model: users and workspaces, papers and their parsed
pages, skills with immutable versions, datasets and their role-tagged files,
experiments with exactly two runs, and the agent-execution record (steps, tool
calls, artifacts, metrics) plus conversations.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_table('workspaces',
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workspaces_user_id'), 'workspaces', ['user_id'], unique=False)
    op.create_table('datasets',
    sa.Column('workspace_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('modality', sa.String(length=60), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_datasets_workspace_id'), 'datasets', ['workspace_id'], unique=False)
    op.create_table('papers',
    sa.Column('workspace_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.String(length=500), nullable=True),
    sa.Column('filename', sa.String(length=300), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_papers_sha256'), 'papers', ['sha256'], unique=False)
    op.create_index(op.f('ix_papers_workspace_id'), 'papers', ['workspace_id'], unique=False)
    op.create_table('dataset_files',
    sa.Column('dataset_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('filename', sa.String(length=300), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('bytes', sa.BigInteger(), nullable=False),
    sa.Column('media_type', sa.String(length=120), nullable=False),
    sa.Column('file_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dataset_files_dataset_id'), 'dataset_files', ['dataset_id'], unique=False)
    op.create_index(op.f('ix_dataset_files_role'), 'dataset_files', ['role'], unique=False)
    op.create_table('paper_pages',
    sa.Column('paper_id', sa.UUID(), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('char_count', sa.Integer(), nullable=False),
    sa.Column('image_storage_key', sa.String(length=500), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('paper_id', 'page_number', name='uq_paper_page')
    )
    op.create_index(op.f('ix_paper_pages_paper_id'), 'paper_pages', ['paper_id'], unique=False)
    op.create_table('skills',
    sa.Column('workspace_id', sa.UUID(), nullable=True),
    sa.Column('paper_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('slug', sa.String(length=300), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_skills_paper_id'), 'skills', ['paper_id'], unique=False)
    op.create_index(op.f('ix_skills_slug'), 'skills', ['slug'], unique=False)
    op.create_index(op.f('ix_skills_workspace_id'), 'skills', ['workspace_id'], unique=False)
    op.create_table('skill_versions',
    sa.Column('skill_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('markdown', sa.Text(), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=False),
    sa.Column('validation', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('extraction_run_id', sa.String(length=64), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('skill_id', 'version', name='uq_skill_version')
    )
    op.create_index(op.f('ix_skill_versions_skill_id'), 'skill_versions', ['skill_id'], unique=False)
    op.create_table('experiments',
    sa.Column('workspace_id', sa.UUID(), nullable=True),
    sa.Column('paper_id', sa.UUID(), nullable=True),
    sa.Column('skill_version_id', sa.UUID(), nullable=True),
    sa.Column('dataset_id', sa.UUID(), nullable=True),
    sa.Column('task_prompt', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['skill_version_id'], ['skill_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_experiments_status'), 'experiments', ['status'], unique=False)
    op.create_index(op.f('ix_experiments_workspace_id'), 'experiments', ['workspace_id'], unique=False)
    op.create_table('conversations',
    sa.Column('workspace_id', sa.UUID(), nullable=True),
    sa.Column('experiment_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['experiment_id'], ['experiments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_conversations_experiment_id'), 'conversations', ['experiment_id'], unique=False)
    op.create_index(op.f('ix_conversations_workspace_id'), 'conversations', ['workspace_id'], unique=False)
    op.create_table('runs',
    sa.Column('experiment_id', sa.UUID(), nullable=True),
    sa.Column('arm', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('thread_id', sa.String(length=64), nullable=True),
    sa.Column('workspace_dir', sa.String(length=300), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('totals', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['experiment_id'], ['experiments.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('experiment_id', 'arm', name='uq_run_experiment_arm')
    )
    op.create_index(op.f('ix_runs_experiment_id'), 'runs', ['experiment_id'], unique=False)
    op.create_index(op.f('ix_runs_status'), 'runs', ['status'], unique=False)
    op.create_index(op.f('ix_runs_thread_id'), 'runs', ['thread_id'], unique=False)
    op.create_table('agent_steps',
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('node', sa.String(length=60), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('detail', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'seq', name='uq_step_run_seq')
    )
    op.create_index(op.f('ix_agent_steps_run_id'), 'agent_steps', ['run_id'], unique=False)
    op.create_table('artifacts',
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('path', sa.String(length=400), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('media_type', sa.String(length=120), nullable=False),
    sa.Column('bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('artifact_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_artifacts_kind'), 'artifacts', ['kind'], unique=False)
    op.create_index(op.f('ix_artifacts_run_id'), 'artifacts', ['run_id'], unique=False)
    op.create_table('messages',
    sa.Column('conversation_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('tool_calls', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_conversation_id'), 'messages', ['conversation_id'], unique=False)
    op.create_table('metrics',
    sa.Column('experiment_id', sa.UUID(), nullable=True),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('scope', sa.String(length=30), nullable=False),
    sa.Column('key', sa.String(length=120), nullable=False),
    sa.Column('value_num', sa.Float(), nullable=True),
    sa.Column('value_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['experiment_id'], ['experiments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_metrics_experiment_id'), 'metrics', ['experiment_id'], unique=False)
    op.create_index(op.f('ix_metrics_key'), 'metrics', ['key'], unique=False)
    op.create_index(op.f('ix_metrics_run_id'), 'metrics', ['run_id'], unique=False)
    op.create_table('tool_calls',
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('step_id', sa.UUID(), nullable=True),
    sa.Column('tool_name', sa.String(length=80), nullable=False),
    sa.Column('args', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['step_id'], ['agent_steps.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tool_calls_run_id'), 'tool_calls', ['run_id'], unique=False)
    op.create_index(op.f('ix_tool_calls_tool_name'), 'tool_calls', ['tool_name'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tool_calls_tool_name'), table_name='tool_calls')
    op.drop_index(op.f('ix_tool_calls_run_id'), table_name='tool_calls')
    op.drop_table('tool_calls')
    op.drop_index(op.f('ix_metrics_run_id'), table_name='metrics')
    op.drop_index(op.f('ix_metrics_key'), table_name='metrics')
    op.drop_index(op.f('ix_metrics_experiment_id'), table_name='metrics')
    op.drop_table('metrics')
    op.drop_index(op.f('ix_messages_conversation_id'), table_name='messages')
    op.drop_table('messages')
    op.drop_index(op.f('ix_artifacts_run_id'), table_name='artifacts')
    op.drop_index(op.f('ix_artifacts_kind'), table_name='artifacts')
    op.drop_table('artifacts')
    op.drop_index(op.f('ix_agent_steps_run_id'), table_name='agent_steps')
    op.drop_table('agent_steps')
    op.drop_index(op.f('ix_runs_thread_id'), table_name='runs')
    op.drop_index(op.f('ix_runs_status'), table_name='runs')
    op.drop_index(op.f('ix_runs_experiment_id'), table_name='runs')
    op.drop_table('runs')
    op.drop_index(op.f('ix_conversations_workspace_id'), table_name='conversations')
    op.drop_index(op.f('ix_conversations_experiment_id'), table_name='conversations')
    op.drop_table('conversations')
    op.drop_index(op.f('ix_experiments_workspace_id'), table_name='experiments')
    op.drop_index(op.f('ix_experiments_status'), table_name='experiments')
    op.drop_table('experiments')
    op.drop_index(op.f('ix_skill_versions_skill_id'), table_name='skill_versions')
    op.drop_table('skill_versions')
    op.drop_index(op.f('ix_skills_workspace_id'), table_name='skills')
    op.drop_index(op.f('ix_skills_slug'), table_name='skills')
    op.drop_index(op.f('ix_skills_paper_id'), table_name='skills')
    op.drop_table('skills')
    op.drop_index(op.f('ix_paper_pages_paper_id'), table_name='paper_pages')
    op.drop_table('paper_pages')
    op.drop_index(op.f('ix_dataset_files_role'), table_name='dataset_files')
    op.drop_index(op.f('ix_dataset_files_dataset_id'), table_name='dataset_files')
    op.drop_table('dataset_files')
    op.drop_index(op.f('ix_papers_workspace_id'), table_name='papers')
    op.drop_index(op.f('ix_papers_sha256'), table_name='papers')
    op.drop_table('papers')
    op.drop_index(op.f('ix_datasets_workspace_id'), table_name='datasets')
    op.drop_table('datasets')
    op.drop_index(op.f('ix_workspaces_user_id'), table_name='workspaces')
    op.drop_table('workspaces')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
