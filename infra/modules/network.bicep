@description('Network and resolver region.')
param location string

@description('Approved VNet CIDR.')
param virtualNetworkPrefix string

@description('GatewaySubnet CIDR.')
param gatewaySubnetPrefix string

@description('Private endpoint subnet CIDR.')
param privateEndpointSubnetPrefix string

@description('DNS inbound subnet CIDR.')
param resolverSubnetPrefix string

@description('DNS inbound static private IP.')
param resolverInboundIp string

@description('Allowed VPN client source CIDR.')
param vpnClientPool string

@description('Cost ownership tags.')
param tags object

resource endpointSecurity 'Microsoft.Network/networkSecurityGroups@2024-07-01' = {
  name: 'nsg-docgen-private-endpoints'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'allow-vpn-blob-https'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: vpnClientPool
          destinationAddressPrefix: privateEndpointSubnetPrefix
        }
      }
      {
        name: 'deny-other-private-endpoint-ingress'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
        }
      }
    ]
  }
}

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2024-07-01' = {
  name: 'vnet-docgen-private'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [virtualNetworkPrefix]
    }
    // Azure DNS Private Resolver does not support VNet encryption.
    encryption: {
      enabled: false
      enforcement: 'AllowUnencrypted'
    }
    subnets: [
      {
        name: 'GatewaySubnet'
        properties: {
          addressPrefix: gatewaySubnetPrefix
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: privateEndpointSubnetPrefix
          privateEndpointNetworkPolicies: 'NetworkSecurityGroupEnabled'
          networkSecurityGroup: {
            id: endpointSecurity.id
          }
        }
      }
      {
        name: 'snet-dns-inbound'
        properties: {
          addressPrefix: resolverSubnetPrefix
          delegations: [
            {
              name: 'dns-resolver'
              properties: {
                serviceName: 'Microsoft.Network/dnsResolvers'
              }
            }
          ]
        }
      }
    ]
  }
}

resource resolver 'Microsoft.Network/dnsResolvers@2025-05-01' = {
  name: 'dnspr-docgen'
  location: location
  tags: tags
  properties: {
    virtualNetwork: {
      id: virtualNetwork.id
    }
  }
}

resource inbound 'Microsoft.Network/dnsResolvers/inboundEndpoints@2025-05-01' = {
  parent: resolver
  name: 'inbound-docgen'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        privateIpAllocationMethod: 'Static'
        privateIpAddress: resolverInboundIp
        subnet: {
          id: '${virtualNetwork.id}/subnets/snet-dns-inbound'
        }
      }
    ]
  }
}

output virtualNetworkId string = virtualNetwork.id
output gatewaySubnetId string = '${virtualNetwork.id}/subnets/GatewaySubnet'
output privateEndpointSubnetId string = '${virtualNetwork.id}/subnets/snet-private-endpoints'
output resolverInboundIp string = inbound.properties.ipConfigurations[0].privateIpAddress
