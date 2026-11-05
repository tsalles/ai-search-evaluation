@description('Private endpoint region.')
param location string

@description('Existing storage account in the deployment resource group.')
param storageAccountName string

@description('VNet linked to private Blob DNS.')
param virtualNetworkId string

@description('Private endpoint subnet with explicit NSG policy.')
param privateEndpointSubnetId string

@description('Cost ownership tags.')
param tags object

resource storageAccount 'Microsoft.Storage/storageAccounts@2025-01-01' existing = {
  name: storageAccountName
}

resource zone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.blob.${environment().suffixes.storage}'
  location: 'global'
  tags: tags
}

resource link 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: zone
  name: 'link-docgen-private'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource endpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: 'pe-saexampledatasource-blob'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'docgen-blob-connection'
        properties: {
          privateLinkServiceId: storageAccount.id
          groupIds: ['blob']
          requestMessage: 'Approved private access for the Entra-authenticated document uploader.'
        }
      }
    ]
  }
}

resource zoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = {
  parent: endpoint
  name: 'blob-dns-zone-group'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob'
        properties: {
          privateDnsZoneId: zone.id
        }
      }
    ]
  }
}

output privateEndpointId string = endpoint.id
output privateDnsZoneId string = zone.id
