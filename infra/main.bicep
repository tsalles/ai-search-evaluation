targetScope = 'resourceGroup'

@description('Region for the approved private-upload network.')
param location string = 'eastus'

@description('Existing storage account. This deployment never redeploys its settings or data.')
param storageAccountName string = 'saexampledatasource'

@description('Non-overlapping VNet CIDR. Keep the conflicting corporate VPN disconnected.')
param virtualNetworkPrefix string = '10.100.0.0/24'

@description('Dedicated GatewaySubnet CIDR, /27 or larger, without an NSG.')
param gatewaySubnetPrefix string = '10.100.0.0/27'

@description('Dedicated Blob private endpoint subnet CIDR.')
param privateEndpointSubnetPrefix string = '10.100.0.32/27'

@description('Dedicated /28 DNS resolver subnet CIDR.')
param resolverSubnetPrefix string = '10.100.0.64/28'

@description('Usable static DNS inbound IP inside the resolver subnet.')
param resolverInboundIp string = '10.100.0.68'

@description('Point-to-site client pool, separate from the VNet and local networks.')
param vpnClientPool string = '10.100.1.0/24'

@description('Tenant authorizing VPN users. Defaults to the selected subscription tenant.')
param tenantId string = subscription().tenantId

var tags = {
  workload: 'docgen-private-vpn'
  environment: 'development'
  managedBy: 'bicep'
}

module network './modules/network.bicep' = {
  name: 'docgen-private-network'
  params: {
    location: location
    virtualNetworkPrefix: virtualNetworkPrefix
    gatewaySubnetPrefix: gatewaySubnetPrefix
    privateEndpointSubnetPrefix: privateEndpointSubnetPrefix
    resolverSubnetPrefix: resolverSubnetPrefix
    resolverInboundIp: resolverInboundIp
    vpnClientPool: vpnClientPool
    tags: tags
  }
}

module storage './modules/private-storage.bicep' = {
  name: 'docgen-private-storage'
  params: {
    location: location
    storageAccountName: storageAccountName
    virtualNetworkId: network.outputs.virtualNetworkId
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    tags: tags
  }
}

module gateway './modules/vpn-gateway.bicep' = {
  name: 'docgen-private-gateway'
  params: {
    location: location
    gatewaySubnetId: network.outputs.gatewaySubnetId
    vpnClientPool: vpnClientPool
    tenantId: tenantId
    tags: tags
  }
}

output gatewayName string = gateway.outputs.gatewayName
output virtualNetworkId string = network.outputs.virtualNetworkId
output resolverInboundIp string = network.outputs.resolverInboundIp
output privateEndpointId string = storage.outputs.privateEndpointId
output privateDnsZoneId string = storage.outputs.privateDnsZoneId
output accountUrl string = 'https://${storageAccountName}.blob.${environment().suffixes.storage}'
output vpnClientPool string = vpnClientPool
