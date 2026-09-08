# Host Profiles

Machine-specific facts and persistent operating-system settings live here.

| Host | Role | Profile |
|---|---|---|
| `casbox` | The whole live system: browser, add-on, native host, Facet runtime, Ollama, accelerators | [../FACET_BRIDGE.md](../FACET_BRIDGE.md#where-these-run) |
| `caspian` | Historical. Earlier Ethnos and benchmark host; not in the live path | [caspian.md](caspian.md) |

There is one machine in the live path, and it is `casbox`. A solve does not
cross a network: the companion runs `facet-remote` as a local subprocess. SSH
is retained only as an explicit transport for a Facet that genuinely runs
elsewhere, and is not the default -- see [the transport
configuration](../FACET_BRIDGE.md#where-the-transport-is-configured).

Shared application defaults live in
[../CURRENT_BASELINE.md](../CURRENT_BASELINE.md). Historical hosts and
superseded optimization reports are available through Git history rather than
the active operating documentation.
