# Liquibase Snowflake POC — Stage File & Notebook Deployments

Proof of concept for organizing a Liquibase changelog around Snowflake
object types that don't fit the usual "DDL against a table" model:

1. **Internal stage file deployments** — e.g. a Cortex Agent / Cortex Analyst
   semantic model YAML file that needs to land on a stage.
2. **Snowflake Notebooks** — an `.ipynb` file that needs to land on a stage
   and then be registered/refreshed as a `NOTEBOOK` object.
3. **Arbitrary scripts into a stage subdirectory** — e.g. a Python file that
   needs to land in a named subfolder (prefix) of an existing stage, rather
   than at its root.

Every changelog and changeset in this POC is written twice, once as XML and
once as YAML, so both are available as a reference — `liquibase.properties`
picks which master changelog (and therefore which format) actually runs.

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
├── changelog-master.xml                   # includes everything below, in order (XML)
├── changelog-master.yaml                  # same, in YAML
└── changesets/
    ├── stages/
    │   ├── 001-create-internal-stages.xml     # CREATE STAGE for all three use cases
    │   └── 001-create-internal-stages.yaml
    ├── semantic-models/
    │   ├── 001-deploy-cortex-semantic-model.xml
    │   ├── 001-deploy-cortex-semantic-model.yaml
    │   └── files/
    │        └── sales_semantic_model.yaml    # the actual YAML that gets PUT
    ├── notebooks/
    │   ├── 001-deploy-notebook.xml
    │   ├── 001-deploy-notebook.yaml
    │   └── files/
    │        └── customer_analysis.ipynb      # the actual notebook that gets PUT
    └── scripts/
        ├── 001-deploy-deduplication-engine.xml
        ├── 001-deploy-deduplication-engine.yaml
        └── files/
            └─── deduplication/     # PUT into a stage subdirectory "deduplication"
                 └─── engine.py
```

Each object type gets its own subfolder with a `files/` directory holding the
real artifact next to the changelog that deploys it — keeps the "what" next
to the "how," and each type can be extended (versioned, added to) independently
of the others.

Each changeset exists as both a `.xml` and a `.yaml` file with identical
behavior. `changelog-master.xml` and `changelog-master.yaml` each `include`
their respective format only — pick one master changelog to run via
`changelogFile` in `liquibase.properties`; don't mix formats within a single
run.

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

## Deploying a file into a stage subdirectory

`changesets/scripts/001-deploy-deduplication-engine.xml` /
`.yaml` shows a third pattern: `PUT` a script into a *subdirectory* (prefix)
of an existing stage rather than the stage root, by appending the
subdirectory path to the stage reference:

```sql
/* source-version: 1 */
PUT file://changesets/scripts/files/deduplication/engine.py
  @CORTEX_SEMANTIC_MODEL_STAGE/deduplication/
  OVERWRITE = TRUE
  AUTO_COMPRESS = FALSE;
```

It reuses `CORTEX_SEMANTIC_MODEL_STAGE` (created in `changesets/stages/`)
rather than creating a new stage — Snowflake stages don't need to be
pre-created per subdirectory, the `deduplication/` prefix is created
implicitly by the `PUT`. This is the pattern to follow for any future
arbitrary file (script, config, etc.) that needs to land under a stage
without becoming its own top-level stage. Same `source-version` comment and
`runOnChange` convention as above applies.

## Running it

1. Download the Snowflake JDBC driver into `drivers/` (or point `classpath`
   in `liquibase.properties` at wherever you keep it).
2. Fill in `liquibase.properties` with real account/warehouse/role values.
3. Pick which master changelog to run by setting `changelogFile` in
   `liquibase.properties` to either `changelog-master.xml` or
   `changelog-master.yaml` (only one should be uncommented at a time).
4. Run from the repo root (PUT's local file paths are resolved relative to
   the working directory):

```bash
liquibase update
```

## Extending this POC

- Add a new semantic model, notebook, or script by dropping the file into
  the relevant `files/` folder and adding a new numbered changeset alongside
  the existing one (`002-deploy-....xml` / `.yaml`) rather than editing
  `001-*` in place, so history stays intact. Keep the XML and YAML versions
  of a changeset in sync — only one format runs per deploy, but both are
  kept as working references.
- If you need role/warehouse-specific stages per environment, parameterize
  the stage name via Liquibase [changelog
  properties](https://docs.liquibase.com/concepts/changelogs/property-substitution.html)
  instead of hardcoding `CORTEX_SEMANTIC_MODEL_STAGE` / `NOTEBOOK_STAGE`.
