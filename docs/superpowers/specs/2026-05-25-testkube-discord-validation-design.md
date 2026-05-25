# Testkube Discord Validation Test

## Overview

Install Testkube into the cluster and create a Go-based validation test that verifies the Hermes Discord bot is authenticated and online in the `jon-agent` namespace.

## Architecture

Install Testkube via Helm (managed by Flux) into `testkube-system` namespace. Create a Go test in the homelab repo that authenticates with Discord, verifies bot presence, and checks channel access. A `TestkubeTest` CRD references the homelab git repo so Testkube can clone, compile, and run the test on demand.

## Components

### 1. `flux/infra/testkube.yaml`
Flux HelmRepository + HelmRelease for the Testkube chart, following the same pattern as `sealed-secrets.yaml`.

### 2. `tests/discord-validation/main.go`
Go test using `github.com/bwmarrin/discordgo` library:
- Creates a discordgo session with the bot token (passed via `DISCORD_BOT_TOKEN` env var)
- Calls `session.User()` to verify authentication
- Checks `session.User().Status` is online
- Calls `session.Channel(HOME_CHANNEL_ID)` to verify bot has access to the home channel
- Returns `t.Fatal()` on any failure

### 3. `tests/discord-validation/go.mod`
Go module with `discordgo` dependency.

### 4. `flux/apps/testkube-discord-validation.yaml`
TestkubeTest CRD with:
- `gitRepositoryURL` pointing to the homelab repo
- `path: tests/discord-validation`
- `runAs: GoTest`
- Secret reference for `DISCORD_BOT_TOKEN` from `hermes-jon-secrets`

## Data Flow

1. User runs: `testkube execute discord-validation -n jon-agent`
2. Testkube reads the `TestkubeTest` CRD, clones the homelab repo at the specified commit
3. Navigates to `tests/discord-validation/`, injects `DISCORD_BOT_TOKEN` from the `hermes-jon-secrets` secret as an env var
4. Runs `go test -v -timeout 60s` — Go downloads `discordgo` module (cached after first run)
5. The test connects to Discord REST API, authenticates, checks presence, checks channel access
6. Testkube captures exit code and logs, displays pass/fail status
7. If the test fails, logs show the exact error (auth failure, timeout, etc.)

## Error Handling

- **Invalid/missing token**: Discord API returns 401 → test fails with "authentication failed"
- **Discord API unreachable**: context deadline exceeded after 60s → test fails with "timeout"
- **Bot offline or not in channel**: test fails with descriptive message about what is missing
- **Retries**: none — one-off test, manual re-run if flaky

## Success Criteria

- Testkube is installed and managed by Flux in `testkube-system`
- `testkube execute discord-validation` runs successfully and reports pass
- Test fails with clear error message when the bot token is invalid or the bot is offline
