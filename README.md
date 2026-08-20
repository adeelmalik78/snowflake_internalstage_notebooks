# Liquibase Snowflake POC — Stage File & Notebook Deployments

Proof of concept for organizing a Liquibase changelog around two Snowflake
object types that don't fit the usual "DDL against a table" model:

1. **Internal stage file deployments** — e.g. a Cortex Agent / Cortex Analyst
   semantic model YAML file that needs to land on a stage.
2. **Snowflake Notebooks** — an `.ipynb` file that needs to land on a stage
   and then be registered/refreshed as a `NOTEBOOK` object.

## Why this shape

Snowflake's JDBC driver has special client-side handling for `PUT`/`GET`
statements — it intercepts them and performs the actual file transfer rather
than sending them to the server as regular SQL. Because Liquibase's `sql`
changeType just forwards its text over the JDBC connection, `PUT` works
inside a normal changeset with no extension or custom changeType needed.

That lets both object types follow the same pattern:

```
1. changeSet: PUT the local file onto an internal stage
2. changeSet: CREATE/ALTER the Snowflake object to point at the staged file
```

## Layout

```
liquibase-snowflake-poc/
├── liquibase.properties
├── changelog-master.yaml                  # includes everything below, in order
└── changesets/
    ├── stages/
    │   └── 001-create-internal-stages.yaml    # CREATE STAGE for both use cases
    ├── semantic-models/
    │   ├── 001-deploy-cortex-semantic-model.yaml
    │   └── files/sales_semantic_model.yaml    # the actual YAML that gets PUT
    └── notebooks/
        ├── 001-deploy-notebook.yaml
        └── files/customer_analysis.ipynb      # the actual notebook that gets PUT
```

Each object type gets its own subfolder with a `files/` directory holding the
real artifact next to the changelog that deploys it — keeps the "what" next
to the "how," and each type can be extended (versioned, added to) independently
of the others.

## Change detection (the one gotcha)

Liquibase decides whether to re-run a `runOnChange` changeset by hashing the
**changeset's own SQL text**, not the contents of any file that SQL happens
to reference. So editing `sales_semantic_model.yaml` or
`customer_analysis.ipynb` alone won't cause the `PUT` changeset to re-fire —
the checksum hasn't moved.

The convention used here: each `PUT` changeset carries a
`/* source-version: N */` comment. Bump `N` whenever the referenced file
changes, and Liquibase's checksum changes with it, triggering a re-run. It's
manual but explicit and requires no extra tooling; if this becomes
error-prone at scale, the natural next step is a pre-commit/CI script that
stamps the comment with a hash of the file automatically.

**Note:** this must be a block comment (`/* ... */`), not a leading `--` line
comment. Snowflake's client-side `PUT`/`GET` interception only fires when
`PUT` is the first token it sees; a leading `--` comment defeats that
detection and the raw statement gets sent to the server instead, which
doesn't understand `PUT` and fails with `Unsupported feature
'unsupported_requested_format:snowflake'`. See [this Snowflake Community
article](https://community.snowflake.com/s/article/PUT-fails-with-error-unsupported-requested-format-snowflake-if-prefixed-by-comment)
for the underlying driver behavior.

For the notebook's "live version" refresh, `ALTER NOTEBOOK ... ADD LIVE
VERSION FROM LAST` is marked `runAlways: true` instead, since that statement
is what actually pulls newly-staged content into the notebook — it needs to
run every deploy, not just once.

## Running it

1. Download the Snowflake JDBC driver into `drivers/` (or point `classpath`
   in `liquibase.properties` at wherever you keep it).
2. Fill in `liquibase.properties` with real account/warehouse/role values.
3. Run from the repo root (PUT's local file paths are resolved relative to
   the working directory):

```bash
liquibase update
```

## Extending this POC

- Add a new semantic model or notebook by dropping the file into the
  relevant `files/` folder and adding a new numbered changeset alongside the
  existing one (`002-deploy-....yaml`) rather than editing `001-*` in place,
  so history stays intact.
- If you need role/warehouse-specific stages per environment, parameterize
  the stage name via Liquibase [changelog
  properties](https://docs.liquibase.com/concepts/changelogs/property-substitution.html)
  instead of hardcoding `CORTEX_SEMANTIC_MODEL_STAGE` / `NOTEBOOK_STAGE`.
