# Host Profiles

These files keep machine-specific setup separate from the project baseline.
Update the matching host profile when hardware, OS, Ollama service settings, or
installed models change.

| Host | Role | Profile |
|---|---|---|
| `erosion` | Local development source host | [`erosion.md`](erosion.md) |
| `caspian` | Migrated CachyOS host | [`caspian.md`](caspian.md) |

Shared app defaults live in [`../PERFORMANCE_TUNING.md`](../PERFORMANCE_TUNING.md)
and [`.env.example`](../../.env.example). Runtime data and model stores are not
tracked by git.
