# Security Policy

## Supported Versions

Only the latest release (and latest pre-release, if you are on the beta
channel) is supported with security fixes.

## Reporting a Vulnerability

Please report vulnerabilities privately via GitHub's
["Report a vulnerability"](https://github.com/chrisc123/jebao_aqua-homeassistant/security/advisories/new)
form rather than opening a public issue.

Things especially worth reporting for this integration:

- Anything that could expose stored Gizwits cloud credentials.
- Ways a device on the local network could crash or take control of the
  integration beyond its own entities (the LAN protocol parser handles
  untrusted input from the network).

This is a spare-time community project, so please allow a reasonable time
for a response - but reports are appreciated and taken seriously.
