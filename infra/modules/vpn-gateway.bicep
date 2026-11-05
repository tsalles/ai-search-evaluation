@description('VPN Gateway region.')
param location string

@description('Dedicated GatewaySubnet without an NSG.')
param gatewaySubnetId string

@description('Non-overlapping P2S VPN client CIDR.')
param vpnClientPool string

@description('Entra tenant authorizing VPN users.')
param tenantId string

@description('Cost ownership tags.')
param tags object

resource publicIp 'Microsoft.Network/publicIPAddresses@2024-07-01' = {
  name: 'pip-docgen-vpn'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  zones: ['1', '2', '3']
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource gateway 'Microsoft.Network/virtualNetworkGateways@2024-07-01' = {
  name: 'vpng-docgen'
  location: location
  tags: tags
  properties: {
    gatewayType: 'Vpn'
    vpnType: 'RouteBased'
    vpnGatewayGeneration: 'Generation1'
    enableBgp: false
    activeActive: false
    sku: {
      name: 'VpnGw1AZ'
      tier: 'VpnGw1AZ'
    }
    ipConfigurations: [
      {
        name: 'gateway-ip-config'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: gatewaySubnetId
          }
          publicIPAddress: {
            id: publicIp.id
          }
        }
      }
    ]
    vpnClientConfiguration: {
      vpnClientAddressPool: {
        addressPrefixes: [vpnClientPool]
      }
      vpnClientProtocols: ['OpenVPN']
      vpnAuthenticationTypes: ['AAD']
      aadTenant: uri(environment().authentication.loginEndpoint, tenantId)
      aadAudience: 'c632b3df-fb67-4d84-bdcf-b95ad541b5c8'
      aadIssuer: 'https://sts.windows.net/${tenantId}/'
    }
  }
}

output gatewayName string = gateway.name
output gatewayId string = gateway.id
