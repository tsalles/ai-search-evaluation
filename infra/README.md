# Private Blob upload network

Status: Example configuration; validate your own environment before deployment

Date: 2026-10-27

These Bicep files illustrate a private upload path to an existing storage account. The `saexampledatasource` account name and network addresses below are examples; replace them with your own values and select your resource group before deployment. The templates reference the account without redeploying its settings or data. Keep storage public access and Shared Key disabled.

## Resources and addressing

| Component | Configuration |
|-----------|---------------|
| VNet | `vnet-docgen-private`, `10.100.0.0/24` |
| Gateway subnet | `GatewaySubnet`, `10.100.0.0/27`, no NSG |
| Private endpoint subnet | `10.100.0.32/27`; NSG permits VPN-client HTTPS and denies other inbound traffic |
| Resolver subnet | `10.100.0.64/28`, delegated to `Microsoft.Network/dnsResolvers` |
| DNS inbound IP | `10.100.0.68` |
| VPN client pool | `10.100.1.0/24` |
| VPN gateway | `vpng-docgen`, `VpnGw1AZ`, route-based OpenVPN with Microsoft Entra authentication |
| Private storage | Blob private endpoint, `privatelink.blob.core.windows.net`, zone group and VNet link |

Use the standalone VPN only when organizational policy permits and conflicting corporate VPN routes are absent. Do not override corporate routing or automatically disconnect another VPN.

VPN gateways, DNS resolvers, and private endpoints can incur charges while clients are disconnected. Review current pricing and your subscription's policies before deployment. Local infrastructure plans and pricing exports are excluded from this public snapshot.

## Deployment prerequisites

Validate the templates against your own environment:

- Compile Bicep and the parameter file.
- Run static policy checks and Azure ARM validation.
- Inspect Azure what-if and reject unintended modifications or deletions.
- Confirm subscription feature availability, resource permissions, and non-overlapping address ranges.

Do not treat successful static validation as proof of deployment or connectivity. Respect subscription policy and existing corporate routes; do not bypass restrictions by enabling account-key access or public storage access.

## Reproducible validation

From the repository root, with Azure CLI/Bicep and Checkov available:

```powershell
az bicep build --file .\infra\main.bicep
az bicep build-params --file .\infra\main.bicepparam --outfile .\infra\main.parameters.json
checkov -d .\infra --framework bicep --compact --quiet
```

Checkov's Bicep scanner also needs the Bicep executable on `PATH`. Generated ARM and parameter JSON files are ignored; source templates and the parameter declaration are versioned.

Before any retry, validate the selected subscription and current routes, run ARM validation/what-if again, and reject changes to existing resources. Use incremental deployment only. Do not delete the whole resource group to remove this infrastructure.

## Required client verification after provisioning

1. Verify the gateway and private endpoint are successfully provisioned and the endpoint connection is approved.
2. Export the gateway's Azure VPN Client profile.
3. Configure that profile with private DNS server `10.100.0.68`, the Blob DNS suffix, and split routing for the VNet. Leave general internet and corporate routing unchanged.
4. Import without overwriting existing profiles, then complete interactive Entra sign-in.
5. Verify the normal storage hostname resolves to the private endpoint IP, TCP 443 reaches it, and an Entra-authenticated container read succeeds.
6. Only then run the [documented corpus upload command](../README.md#upload-a-corpus-to-azure-blob-storage).

Use your storage account's normal Blob hostname; the illustrative URL is `https://saexampledatasource.blob.core.windows.net`. Do not replace it with a private IP or `privatelink` URL.
