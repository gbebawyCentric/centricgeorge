# Letting a Claude Code session deploy to Sigma

Setup for running `scripts/deploy.py` from inside a Claude Code remote session
rather than a laptop. Two things have to be configured on the **environment**,
both by whoever administers it. Neither can be set from inside a session, and
both only take effect in sessions started afterwards.

Environment settings live in the Claude Code environment configuration on
claude.ai. See
<https://code.claude.com/docs/en/claude-code-on-the-web> for where they are and
what the network-policy options mean.

## 1. Allow the Sigma hosts

By default the egress policy rejects these at the gateway — the session sees
`403 to CONNECT` before any traffic leaves, and it cannot be worked around from
inside the session.

| Host | Needed for |
|---|---|
| `api.us.azure.sigmacomputing.com` | The API itself. This is the Azure-US host, which is the cloud Centric Brands is on (Azure East US 2, Virginia). It must match `SIGMA_API_BASE_URL`. |
| `help.sigmacomputing.com` | Sigma docs, including the workbooks-as-code spec reference |

Allowlist only the one host that matches `SIGMA_API_BASE_URL`. The other Sigma
API hosts stay policy-denied, which is a useful guard: a session cannot silently
authenticate against the wrong cloud, it fails at the gateway instead.

An earlier version of this file allowlisted `aws-api.sigmacomputing.com`, which
is the AWS-US West host and belongs to no Sigma org of ours. Deploys failed
against it with `HTTP 400 Invalid access/refresh token` — the credential was
fine, the cloud was wrong, and the error does not distinguish the two. If the
allowlist and `SIGMA_API_BASE_URL` ever disagree, that is the symptom.

To confirm it worked, from a new session:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://api.us.azure.sigmacomputing.com/v2/auth/token
```

Anything other than `000` means the tunnel is open. A `403` recorded against
the *host* in `curl -sS "$HTTPS_PROXY/__agentproxy/status"` means it is still
policy-denied.

## 2. Supply the credentials as environment variables

Set these in the environment configuration. Do **not** paste them into a chat
message — that records them in the transcript, where they persist and are not
covered by rotation.

| Variable | Value |
|---|---|
| `SIGMA_CLIENT_ID` | Client id |
| `SIGMA_CLIENT_SECRET` | Client secret |
| `SIGMA_API_BASE_URL` | API host, matching the allowlisted one above |
| `SIGMA_WORKSPACE_ID` | Optional — workspace new workbooks are created in |

The scripts read only from the environment, so with these set a session can run
`python3 scripts/deploy.py` directly and no `.env` file is involved. The local
`.env` flow in the README stays valid for laptop runs; the two do not conflict.

## Before you turn this on

An environment variable is readable by everything in every session on that
environment, and by anyone who can start one. Treat it as a shared service
credential, not a personal one:

- **Use a dedicated Sigma service account**, not an individual's admin
  credential. Sessions inherit whatever it can do — if it can delete production
  workbooks, so can any session.
- **Scope it** to the workspace these workbooks live in.
- **Rotate** if the value is ever echoed into a transcript, a log, or a commit.
  Sigma shows a client secret once at creation, so rotating means issuing a new
  credential and updating the environment.
- Sigma credentials are **not** needed to run anything in `sql/`. Those go
  through the Snowflake connector and are unaffected by all of this.

## What still will not work

Snowflake is certificate-pinned and is on the proxy's unsupported list, so a
session cannot connect to it directly even with an allowlist entry. Running the
queries in `sql/` from a session means going through the Snowflake MCP
connector, which is how they were validated in the first place. This does not
affect `deploy.py`, which only talks to Sigma.
