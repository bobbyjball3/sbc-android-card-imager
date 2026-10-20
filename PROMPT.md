> **SUPERSEDED.** This is the original kickoff brief for the retired
> Python/Typer CLI device-imaging design. The project now uses an Ansible +
> container + `dd`/Etcher pipeline; see [README.md](README.md) for the
> current architecture and [AGENTS.md](AGENTS.md) for working rules. Kept
> below for historical context only.

# SD Card Imager for SBC Devices

I want to build a repository that allows me to:
- Specify APKs to include as files in the image
- Specify Overlays to include (both local includes and remote like git repos or file links)
- Specify Shaders to include (both local includes and remote like git repos or file links)
- Specify any other local artifacts and a directory structure
- Build a sparse image in the correct format (exfat I believe by default)
- optional task target to image a specified device

I would like the tool to be CLI-driven so that all of the build code can be tested. Then Task tasks execute the CLI. 
- Use entrypoints to produce utility script
- Use Typer as the CLI framework - I want to try that out
- You can add other dependencies - ensure you add them to the correct group (dev vs. runtime deps)

For the imaging, If it's easily doable in Python that's fine. But it would also be acceptable to use things like DD etc. Just make sure if you do execute something like DD you output progress and report on it in the CLI itself.

There's a lot of unknown here, so interview me to close any and all gaps to allow you to build a very detailed plan for execution.

Follow all rules in [AGENTS.md](AGENTS.md) to the T.