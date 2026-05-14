from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0045_organization_profile_fields'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE TABLE IF NOT EXISTS account_socialnetwork (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    name VARCHAR(100) NOT NULL UNIQUE,
                    logo VARCHAR(100)
                );

                ALTER TABLE account_organizationsociallink
                    DROP COLUMN IF EXISTS platform,
                    DROP COLUMN IF EXISTS logo;

                ALTER TABLE account_organizationsociallink
                    ADD COLUMN IF NOT EXISTS social_network_id BIGINT
                        REFERENCES account_socialnetwork(id) DEFERRABLE INITIALLY DEFERRED;

                ALTER TABLE account_organizationsociallink
                    DROP CONSTRAINT IF EXISTS account_organizationsociallink_organization_id_platform_key;

                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'account_organizationsociallink_organization_id_social_netw_key'
                    ) THEN
                        ALTER TABLE account_organizationsociallink
                            ADD CONSTRAINT account_organizationsociallink_organization_id_social_netw_key
                            UNIQUE (organization_id, social_network_id);
                    END IF;
                END $$;
            """,
            reverse_sql="""
                ALTER TABLE account_organizationsociallink
                    DROP COLUMN IF EXISTS social_network_id,
                    ADD COLUMN IF NOT EXISTS platform VARCHAR(50),
                    ADD COLUMN IF NOT EXISTS logo VARCHAR(100);

                DROP TABLE IF EXISTS account_socialnetwork;
            """,
        ),
    ]
