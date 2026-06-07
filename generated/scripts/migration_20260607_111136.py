from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'initial_blog_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('username', sa.String(50), unique=True, nullable=False),
        sa.Column('email', sa.String(100), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_table(
        'posts',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('published_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_table(
        'comments',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('post_id', sa.Integer, sa.ForeignKey('posts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
    )

    op.create_index('idx_posts_user_id', 'posts', ['user_id'])
    op.create_index('idx_comments_post_id', 'comments', ['post_id'])
    op.create_index('idx_comments_user_id', 'comments', ['user_id'])
    op.create_index('idx_posts_created_at', 'posts', ['created_at'], postgresql_using='btree')
    op.create_index('idx_posts_published_at', 'posts', ['published_at'], postgresql_where=sa.text('published_at IS NOT NULL'), postgresql_using='btree')

    # Add triggers for updated_at
    op.execute("""
        CREATE OR REPLACE FUNCTION update_timestamp()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER set_user_updated_at
        BEFORE UPDATE ON users
        FOR EACH ROW
        EXECUTE FUNCTION update_timestamp();
    """)
    op.execute("""
        CREATE TRIGGER set_post_updated_at
        BEFORE UPDATE ON posts
        FOR EACH ROW
        EXECUTE FUNCTION update_timestamp();
    """)
    op.execute("""
        CREATE TRIGGER set_comment_updated_at
        BEFORE UPDATE ON comments
        FOR EACH ROW
        EXECUTE FUNCTION update_timestamp();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS set_comment_updated_at ON comments;")
    op.execute("DROP TRIGGER IF EXISTS set_post_updated_at ON posts;")
    op.execute("DROP TRIGGER IF EXISTS set_user_updated_at ON users;")
    op.execute("DROP FUNCTION IF EXISTS update_timestamp();")

    op.drop_index('idx_posts_published_at', table_name='posts')
    op.drop_index('idx_posts_created_at', table_name='posts')
    op.drop_index('idx_comments_user_id', table_name='comments')
    op.drop_index('idx_comments_post_id', table_name='comments')
    op.drop_index('idx_posts_user_id', table_name='posts')

    op.drop_table('comments')
    op.drop_table('posts')
    op.drop_table('users')